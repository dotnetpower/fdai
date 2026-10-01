"""Audit-gated privileged execution phase owned exclusively by Thor."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from copy import deepcopy
from datetime import timedelta
from typing import Any, Protocol

from fdai.agents._framework import thor_preflight
from fdai.agents._framework.action_run_state import ActionRunState
from fdai.agents._framework.thor_action_run import ActionRun, ActionRunStore
from fdai.core.executor.safeguards import resource_lock_key
from fdai.core.operational_context.test_context_dispatch import (
    TestContextDispatchGuard,
    TestContextDispatchHold,
)
from fdai.shared.contracts.models import Autonomy
from fdai.shared.providers.resource_lock import ResourceLock


class ExecutionResourceUnavailableError(RuntimeError):
    """The cross-replica mutation lock could not be acquired."""


class ThorExecutionHost(Protocol):
    _executor: Callable[[dict[str, Any]], Awaitable[bool]]
    _executor_timeout_seconds: float
    _effect_verification_timeout_seconds: int
    _execution_audit_timeout_seconds: float
    _execution_audit_recorder: Callable[[ActionRun], Awaitable[str]] | None
    _require_execution_audit: bool
    _preflight_simulator: thor_preflight.ThorPreflightSimulator | None
    _preflight_timeout_seconds: float
    _preflight_receipt_ttl_seconds: int
    _execution_resource_lock: ResourceLock | None
    _require_execution_resource_lock: bool
    _state_store: ActionRunStore | None
    _test_context_dispatch_guard: TestContextDispatchGuard | None

    def _must_shadow(self) -> bool: ...

    def _revalidate_development_authority(self, run: ActionRun) -> None: ...

    def _now(self) -> Any: ...

    async def _emit_action_run(self, run: ActionRun) -> None: ...

    async def _release_resource_claim(self, run: ActionRun) -> None: ...

    def _release_lock(self, resource_id: Any) -> None: ...

    def record_behavior(self, key: str) -> None: ...


async def execute(host: ThorExecutionHost, run: ActionRun) -> None:
    """Drive one authorized run through audit, lock, executor, and terminal state."""
    release_run_lock = False
    try:
        run.shadow_mode = (
            run.shadow_mode
            or run.resolved_autonomy_ceiling is Autonomy.SHADOW_ONLY
            or host._must_shadow()
        )
        if run.test_context_guard is not None:
            guard = host._test_context_dispatch_guard
            hold = TestContextDispatchHold()
            if guard is None or not await guard.current(
                run.test_context_guard, target_ref=run.resource_id, hold=hold
            ):
                run.transition(ActionRunState.DENY_DROPPED)
                run.outcome = hold.outcome
                run.evidence_rejection_ref = hold.rejection_ref
                await host._emit_action_run(run)
                await host._release_resource_claim(run)
                host.record_behavior("test_context:dispatch_held")
                release_run_lock = True
                return
        if run.shadow_mode:
            run.transition(ActionRunState.EXECUTING)
            await host._emit_action_run(run)
            run.transition(ActionRunState.SUCCEEDED)
            run.outcome = "shadow_success"
            await host._emit_action_run(run)
            await host._release_resource_claim(run)
            host.record_behavior("executed:shadow")
            release_run_lock = True
            return
        if await preflight_blocks_execution(host, run):
            await host._emit_action_run(run)
            await host._release_resource_claim(run)
            release_run_lock = True
            return
        if not run.shadow_mode and host._require_execution_audit:
            recorder = host._execution_audit_recorder
            if recorder is None:
                run.transition(ActionRunState.DENY_DROPPED)
                run.outcome = "execution_audit_unavailable"
                await host._emit_action_run(run)
                await host._release_resource_claim(run)
                host.record_behavior("execution_audit:unavailable")
                release_run_lock = True
                return
            try:
                async with asyncio.timeout(host._execution_audit_timeout_seconds):
                    receipt = await recorder(run)
            except TimeoutError:
                run.transition(ActionRunState.DENY_DROPPED)
                run.outcome = "execution_audit_timeout"
                await host._emit_action_run(run)
                await host._release_resource_claim(run)
                host.record_behavior("execution_audit:timeout")
                release_run_lock = True
                return
            except Exception:  # noqa: BLE001 - audit failure blocks executor I/O
                run.transition(ActionRunState.DENY_DROPPED)
                run.outcome = "execution_audit_failed"
                await host._emit_action_run(run)
                await host._release_resource_claim(run)
                host.record_behavior("execution_audit:failed")
                release_run_lock = True
                return
            if not receipt.strip() or len(receipt) > 512:
                run.transition(ActionRunState.DENY_DROPPED)
                run.outcome = "execution_audit_invalid"
                await host._emit_action_run(run)
                await host._release_resource_claim(run)
                host.record_behavior("execution_audit:invalid")
                release_run_lock = True
                return
            run.execution_audit_receipt = receipt
            host.record_behavior("execution_audit:recorded")
        if not run.shadow_mode and not run.resource_claimed:
            try:
                host._revalidate_development_authority(run)
            except ValueError:
                run.transition(ActionRunState.DENY_DROPPED)
                run.outcome = "development_authority_revalidation_failed"
                await host._emit_action_run(run)
                await host._release_resource_claim(run)
                host.record_behavior("development_authority:revalidation_failed")
                release_run_lock = True
                return
            if not await claim_execution_resource(host, run):
                run.transition(ActionRunState.DENY_DROPPED)
                run.outcome = "duplicate_execution_already_completed"
                await host._emit_action_run(run)
                host._release_lock(run.resource_id)
                return
        run.transition(ActionRunState.EXECUTING)
        await host._emit_action_run(run)
        try:
            async with asyncio.timeout(host._executor_timeout_seconds):
                success = await invoke_executor(host, run)
        except ExecutionResourceUnavailableError as exc:
            retry_state = (
                ActionRunState.APPROVED if run.verdict == "hil" else ActionRunState.VERDICTED
            )
            run.transition(retry_state)
            run.outcome = "execution_resource_temporarily_unavailable"
            await host._emit_action_run(run)
            host.record_behavior("execution_resource_lock:unavailable")
            raise RuntimeError("execution resource is temporarily unavailable") from exc
        except TimeoutError:
            run.transition(ActionRunState.EXECUTION_UNKNOWN)
            run.outcome = "executor_timeout"
            await host._emit_action_run(run)
            host.record_behavior("executed:unknown")
            return
        except Exception as exc:  # noqa: BLE001 - surface adapter errors become failure evidence
            success = False
            run.outcome = f"executor_error:{type(exc).__name__}"
        if run.outcome == "command_accepted_lock_release_unknown":
            run.transition(ActionRunState.EXECUTION_UNKNOWN)
            await host._emit_action_run(run)
            host.record_behavior("executed:unknown")
            return
        run.transition(ActionRunState.EFFECT_PENDING if success else ActionRunState.FAILED)
        if success and run.outcome is None:
            run.outcome = "command_accepted_verification_pending"
            run.effect_verification_expires_at = host._now() + timedelta(
                seconds=host._effect_verification_timeout_seconds
            )
        if not success and run.outcome is None:
            run.outcome = "executor returned false"
        await host._emit_action_run(run)
        host.record_behavior("executed:success" if success else "executed:failed")
        release_run_lock = False
    finally:
        if release_run_lock:
            host._release_lock(run.resource_id)


async def preflight_blocks_execution(host: ThorExecutionHost, run: ActionRun) -> bool:
    """Run or reuse Thor's pre-flight simulation before privileged executor I/O."""

    if not thor_preflight.requires_preflight(run):
        return False
    now = host._now()
    if thor_preflight.receipt_is_fresh(
        run.preflight_simulation_receipt,
        run=run,
        now=now,
        ttl_seconds=host._preflight_receipt_ttl_seconds,
    ):
        host.record_behavior("preflight:reused")
        return False
    simulator = host._preflight_simulator
    if simulator is None:
        run.transition(ActionRunState.DENY_DROPPED)
        run.outcome = "preflight_unavailable"
        host.record_behavior("preflight:unavailable")
        return True
    run_snapshot = ActionRun.from_dict(run.to_dict())
    identity_before = run_snapshot.action_run_identity()
    started_at = host._now()
    try:
        async with asyncio.timeout(host._preflight_timeout_seconds):
            result = await simulator.simulate(deepcopy(run_snapshot))
    except TimeoutError:
        run.transition(ActionRunState.DENY_DROPPED)
        run.outcome = "preflight_timeout"
        host.record_behavior("preflight:timeout")
        return True
    except Exception:  # noqa: BLE001 - simulator errors fail closed before executor I/O
        run.transition(ActionRunState.DENY_DROPPED)
        run.outcome = "preflight_error"
        host.record_behavior("preflight:error")
        return True
    completed_at = host._now()
    if run.action_run_identity() != identity_before:
        run.transition(ActionRunState.DENY_DROPPED)
        run.outcome = "preflight_error"
        host.record_behavior("preflight:error")
        return True
    receipt = thor_preflight.build_receipt(
        run=run_snapshot,
        result=result,
        started_at=started_at,
        completed_at=completed_at,
    )
    run.preflight_simulation_receipt = receipt
    run.dry_run_evidence = "thor_preflight_simulation"
    run.dry_run_receipt = str(receipt["receipt_digest"])
    await host._emit_action_run(run)
    if result.outcome != "passed":
        run.transition(ActionRunState.DENY_DROPPED)
        run.outcome = "preflight_failed"
        host.record_behavior("preflight:failed")
        return True
    host.record_behavior("preflight:passed")
    return False


async def invoke_executor(host: ThorExecutionHost, run: ActionRun) -> bool:
    """Invoke the bound executor under the optional cross-replica resource lock."""
    host._revalidate_development_authority(run)
    resource_id = str(run.resource_id or "")
    if not resource_id:
        raise ValueError("execution resource_id MUST be non-empty")
    resource_lock = host._execution_resource_lock
    if resource_lock is None:
        if host._require_execution_resource_lock:
            raise RuntimeError("cross-replica execution resource lock is unavailable")
        return await host._executor({"run": run})
    context = resource_lock.acquire(resource_lock_key(resource_id))
    try:
        await context.__aenter__()
    except Exception as exc:
        raise ExecutionResourceUnavailableError from exc
    if run.resource_claimed:
        try:
            lease_seconds = getattr(host._state_store, "claim_lease_seconds", None)
            refresh_claim = getattr(host._state_store, "refresh_resource_claim", None)
            if (
                isinstance(lease_seconds, bool)
                or not isinstance(lease_seconds, int)
                or lease_seconds <= host._executor_timeout_seconds
                or not callable(refresh_claim)
                or not await refresh_claim(run)
            ):
                raise ExecutionResourceUnavailableError
            validate_claim = getattr(host._state_store, "validate_resource_claim", None)
            if not callable(validate_claim) or not await validate_claim(run):
                raise ExecutionResourceUnavailableError
        except asyncio.CancelledError:
            try:
                await context.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001 - preserve cancellation semantics
                host.record_behavior("execution_resource_lock:release_unknown")
            raise
        except Exception as exc:
            try:
                await context.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001 - preserve non-execution classification
                host.record_behavior("execution_resource_lock:release_unknown")
            raise ExecutionResourceUnavailableError from exc
    if run.outcome == "execution_resource_temporarily_unavailable":
        run.outcome = None
    try:
        result = await host._executor({"run": run})
    except BaseException as exc:
        try:
            await context.__aexit__(type(exc), exc, exc.__traceback__)
        except Exception:  # noqa: BLE001 - preserve cancellation/timeout ambiguity
            host.record_behavior("execution_resource_lock:release_unknown")
        raise
    try:
        await context.__aexit__(None, None, None)
    except Exception:  # noqa: BLE001 - mutation result remains unknown, never failed
        run.outcome = "command_accepted_lock_release_unknown"
        host.record_behavior("execution_resource_lock:release_unknown")
    return result


async def claim_execution_resource(host: ThorExecutionHost, run: ActionRun) -> bool:
    """Claim the durable mutation identity before any privileged executor I/O."""
    if run.resource_claimed:
        return True
    claim = getattr(host._state_store, "claim_resource", None)
    if not callable(claim):
        if host._require_execution_resource_lock:
            raise ExecutionResourceUnavailableError
        return True
    result = await claim(run)
    if result == "completed":
        run.resource_claimed = False
        return False
    if result != "acquired":
        run.resource_claimed = False
        raise ExecutionResourceUnavailableError
    run.resource_claimed = True
    return True


__all__ = [
    "ExecutionResourceUnavailableError",
    "claim_execution_resource",
    "execute",
    "invoke_executor",
    "preflight_blocks_execution",
]
