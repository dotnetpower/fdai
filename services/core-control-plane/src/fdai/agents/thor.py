"""Thor - Responder (Wave 3 behavior).

Thor dispatches verdicts. It enforces per-resource mutex, tracks
ActionRun state through the lifecycle, requests HIL approval via Var,
and triggers rollback via Vidar on failure.

Hard dependencies (per pantheon 4.3):
- Saga must be reachable (audit chain must accept appends) - degrades
  new mutations to shadow when absent.
- Vidar must be reachable - degrades new mutations to shadow when
  absent.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from weakref import WeakValueDictionary

from fdai.agents._framework import (
    action_run_lineage,
    thor_dispatch_validation,
    thor_execution,
    thor_introspection,
    thor_persistence,
)
from fdai.agents._framework.action_run_identity import (
    approval_matches_action_run,
    bounded_rollback_ref,
    rollback_matches_action_run,
)
from fdai.agents._framework.action_run_lineage import (
    bounded_operational_context as _bounded_operational_context,
)
from fdai.agents._framework.action_run_state import (
    TERMINAL_ACTION_RUN_STATES as _TERMINAL_STATES,
)
from fdai.agents._framework.action_run_state import ActionRunState
from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.introspection import IntrospectionResult
from fdai.agents._framework.pantheon import _THOR
from fdai.agents._framework.thor_action_run import (
    ActionRun,
    ActionRunStore,
)
from fdai.agents._framework.thor_action_run import (
    kinetic_proposal as _kinetic_proposal,
)
from fdai.agents._framework.thor_action_run import (
    kinetic_proposal_matches as _kinetic_proposal_matches,
)
from fdai.agents._framework.thor_action_run import (
    prospective_lineage as _prospective_lineage,
)
from fdai.agents._framework.thor_correlation import resolve_correlation_claim
from fdai.agents._framework.thor_effect_verification import ThorEffectVerificationMixin
from fdai.agents._framework.thor_execution import (
    ExecutionResourceUnavailableError as _ExecutionResourceUnavailableError,
)
from fdai.core.operational_context.test_context_dispatch import (
    TestContextDispatchBinding,
    TestContextDispatchGuard,
)
from fdai.shared.contracts.models import Autonomy
from fdai.shared.providers.resource_lock import ResourceLock

_resolved_autonomy_ceiling = thor_dispatch_validation.resolved_autonomy_ceiling
_selected_action_matches = thor_dispatch_validation.selected_action_matches

ActionExecutor = Callable[[dict[str, Any]], Awaitable[bool]]
"""Callable that mutates the target and returns True on success."""

ExecutionAuditRecorder = Callable[["ActionRun"], Awaitable[str]]
"""Persist one Saga-owned pre-execution intent and return its receipt id."""


class _ReentrantAsyncLock:
    """Serialize a correlation while allowing synchronous bus callbacks in one task."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task[Any] | None = None
        self._depth = 0

    async def __aenter__(self) -> None:
        current = asyncio.current_task()
        if current is not None and current is self._owner:
            self._depth += 1
            return
        await self._lock.acquire()
        self._owner = current
        self._depth = 1

    async def __aexit__(self, *_args: object) -> None:
        if asyncio.current_task() is not self._owner:
            raise RuntimeError("correlation lock released by a non-owner task")
        self._depth -= 1
        if self._depth == 0:
            self._owner = None
            self._lock.release()


class Thor(ThorEffectVerificationMixin, Agent):
    """Wave-3 Thor: dispatcher + per-resource mutex + lifecycle owner."""

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        executor: ActionExecutor | None = None,
        shadow_required: Callable[[], bool] | None = None,
        shadow_by_default: bool = False,
        saga_available: bool = True,
        vidar_available: bool = True,
        state_store: ActionRunStore | None = None,
        execution_audit_recorder: ExecutionAuditRecorder | None = None,
        require_execution_audit: bool = False,
        hil_timeout_seconds: int = 3_600,
        executor_timeout_seconds: float = 300.0,
        clock: Callable[[], datetime] | None = None,
        execution_resource_lock: ResourceLock | None = None,
        require_execution_resource_lock: bool = False,
    ) -> None:
        if isinstance(hil_timeout_seconds, bool) or hil_timeout_seconds < 1:
            raise ValueError("hil_timeout_seconds MUST be a positive integer")
        if executor_timeout_seconds <= 0:
            raise ValueError("executor_timeout_seconds MUST be > 0")
        super().__init__(spec=_THOR)
        self.bus = bus
        self._executor = executor or _default_executor
        self._shadow_required = shadow_required or (lambda: False)
        self._shadow_by_default = shadow_by_default
        self._saga_available = saga_available
        self._vidar_available = vidar_available
        self._state_store = state_store
        self._execution_audit_recorder = execution_audit_recorder
        self._require_execution_audit = require_execution_audit
        self._hil_timeout_seconds = hil_timeout_seconds
        self._executor_timeout_seconds = executor_timeout_seconds
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._execution_resource_lock = execution_resource_lock
        self._require_execution_resource_lock = require_execution_resource_lock
        self._test_context_dispatch_guard: TestContextDispatchGuard | None = None
        self.action_runs: dict[str, ActionRun] = {}
        self._idempotency_runs: dict[str, ActionRun] = {}
        self._resource_locks: set[str] = set()
        self._correlation_locks: WeakValueDictionary[str, _ReentrantAsyncLock] = (
            WeakValueDictionary()
        )
        self._resource_dispatch_locks: WeakValueDictionary[str, asyncio.Lock] = (
            WeakValueDictionary()
        )
        # FIFO-cap terminal history; active runs retain resource mutex and approval lookups.
        self._max_retained_runs = 10_000

    def bind_test_context_dispatch_guard(self, guard: TestContextDispatchGuard) -> None:
        """Bind an authority-lowering context recheck before processing runtime events."""
        if self._test_context_dispatch_guard is not None:
            raise RuntimeError("test context dispatch guard is already bound")
        self._test_context_dispatch_guard = guard

    def set_executor(self, executor: ActionExecutor) -> None:
        """Bind the composition root's privileged action executor."""
        self._executor = executor

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    def set_state_store(self, store: ActionRunStore) -> None:
        """Attach a durable ActionRun store (composition-root seam)."""
        self._state_store = store

    def set_execution_audit_recorder(
        self,
        recorder: ExecutionAuditRecorder | None,
        *,
        required: bool,
    ) -> None:
        """Bind the durable Saga-owned intent recorder used before executor I/O."""

        self._execution_audit_recorder = recorder
        self._require_execution_audit = required

    def set_execution_resource_lock(
        self,
        resource_lock: ResourceLock | None,
        *,
        required: bool,
    ) -> None:
        """Bind the cross-replica mutation lock required by enforce mode."""

        self._execution_resource_lock = resource_lock
        self._require_execution_resource_lock = required

    async def rehydrate(self) -> int:
        return await thor_persistence.rehydrate(self)

    async def _resume_rehydrated(self, run: ActionRun) -> None:
        await thor_persistence.resume_rehydrated(self, run)

    def set_shadow(self, enabled: bool) -> None:
        """Force shadow mode on / off for every future dispatch.

        The composition root (:class:`~fdai.agents.runtime.PantheonRuntime`)
        calls this to keep the pantheon Thor judge-and-log only, so it
        never double-executes alongside the P1 control loop. Enforce is an
        explicit, separately reviewed promotion - never the default.
        """
        self._shadow_by_default = enabled

    def set_shadow_required(self, predicate: Callable[[], bool]) -> None:
        """Bind a live fail-closed authority predicate for future execution."""
        self._shadow_required = predicate

    def _must_shadow(self) -> bool:
        if self._shadow_by_default:
            return True
        try:
            return self._shadow_required()
        except Exception:  # noqa: BLE001 - authority-provider failure must fail closed
            self.record_behavior("authority:unavailable")
            return True

    def health(self) -> dict[str, Any]:
        """Expose dispatcher state for Heimdall's probe / runtime health."""
        active = sum(1 for r in self.action_runs.values() if r.state not in _TERMINAL_STATES)
        return {
            "agent": "Thor",
            "status": "ok",
            "active_runs": active,
            "retained_runs": len(self.action_runs),
            "locked_resources": len(self._resource_locks),
            "shadow_forced": self._shadow_by_default,
            "behavior": self.behavior_snapshot(),
        }

    # ---- typed port ----------------------------------------------------

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if payload.get("kind") in {"human_assignment", "handover_knowledge"}:
            self.record_behavior("assignment_non_action_ignored")
            return
        if topic == "object.verdict":
            if payload.get("kind") == "document_ingestion":
                self.record_behavior("document_verdict_ignored")
                return
            if payload.get("kind") == "architecture_review":
                self.record_behavior("architecture_review_verdict_ignored")
                return
            if payload.get("kind") == "capacity_graduation":
                self.record_behavior("capacity_graduation_verdict_ignored")
                return
            if not payload.get("action_type") and payload.get("reason") in {
                "anomaly_action_unavailable",
                "no_rule_match",
            }:
                self.record_behavior("non_action_verdict_ignored")
                return
            await self.dispatch_verdict(payload)
        elif topic == "object.approval":
            if payload.get("kind") == "test_context_review":
                self.record_behavior("test_context_approval_ignored")
                return
            if payload.get("kind") == "document_ingestion":
                self.record_behavior("document_approval_ignored")
                return
            if payload.get("kind") != "action":
                self.record_behavior("non_action_approval_ignored")
                return
            await self._handle_approval(payload)
        elif topic == "object.rollback":
            await self._handle_rollback(payload)
        elif topic == "object.recovery-effect-observation":
            await self._handle_effect_observation(payload)

    # ---- lifecycle -----------------------------------------------------

    async def dispatch_verdict(self, verdict: dict[str, Any]) -> ActionRun:
        """Serialize duplicate delivery for one correlation before dispatch."""

        correlation = str(verdict.get("correlation_id", ""))
        lock = self._correlation_locks.setdefault(correlation, _ReentrantAsyncLock())
        async with lock:
            resource_id = str(verdict.get("resource_id") or "")
            if resource_id:
                resource_lock = self._resource_dispatch_locks.setdefault(
                    resource_id,
                    asyncio.Lock(),
                )
                async with resource_lock:
                    return await self._dispatch_verdict_once(verdict)
            return await self._dispatch_verdict_once(verdict)

    async def _dispatch_verdict_once(self, verdict: dict[str, Any]) -> ActionRun:
        correlation = str(verdict.get("correlation_id", ""))
        action_type = str(verdict.get("action_type", ""))
        risk_verdict = str(verdict.get("risk_verdict", "hil"))
        resolved_autonomy_ceiling = _resolved_autonomy_ceiling(verdict)
        if resolved_autonomy_ceiling is Autonomy.ENFORCE_HIL and risk_verdict == "auto":
            risk_verdict = "hil"
        resource_id = verdict.get("resource_id")
        raw_decision_case = verdict.get("decision_case")
        decision_case = action_run_lineage.bounded_decision_case(raw_decision_case)
        raw_params = verdict.get("params")
        params = deepcopy(dict(raw_params)) if isinstance(raw_params, Mapping) else {}
        operational_context = _bounded_operational_context(verdict.get("operational_context"))
        if verdict.get("operational_context") is not None and operational_context is None:
            resolved_autonomy_ceiling = Autonomy.SHADOW_ONLY
        raw_kinetic_proposal = verdict.get("kinetic_proposal")
        kinetic_proposal = _kinetic_proposal(raw_kinetic_proposal)
        raw_prospective_lineage = verdict.get("prospective_lineage")
        prospective_lineage = _prospective_lineage(raw_prospective_lineage)
        semantic_arbitration = verdict.get("reason") in {
            "arbitration_resolved",
            "arbitration_unresolved",
        }
        invalid_decision_case = raw_decision_case is not None and (
            decision_case is None
            or not action_type
            or not _selected_action_matches(decision_case, action_type)
        )
        invalid_kinetic_proposal = raw_kinetic_proposal is not None and (
            kinetic_proposal is None
            or not _kinetic_proposal_matches(
                kinetic_proposal,
                correlation_id=correlation,
                action_type=action_type,
                resource_id=resource_id,
                params=params,
                decision_case=decision_case,
            )
        )
        invalid_prospective_lineage = raw_prospective_lineage is not None and (
            prospective_lineage is None
            or kinetic_proposal is None
            or prospective_lineage.correlation_id != correlation
            or prospective_lineage.proposal_id != kinetic_proposal.proposal_id
            or prospective_lineage.operational_plan_id != kinetic_proposal.operational_plan_id
            or prospective_lineage.mutation_plan_digest != kinetic_proposal.plan.digest
        )
        if (
            (semantic_arbitration and decision_case is None)
            or invalid_decision_case
            or invalid_kinetic_proposal
            or invalid_prospective_lineage
        ):
            risk_verdict = "deny"
            action_type = ""
            kinetic_proposal = None
            prospective_lineage = None
            if invalid_kinetic_proposal:
                self.record_behavior("kinetic_proposal:invalid")
            if invalid_prospective_lineage:
                self.record_behavior("prospective_lineage:invalid")
        elif kinetic_proposal is not None:
            self.record_behavior("kinetic_proposal:validated")

        # Idempotency: at-least-once delivery means the same verdict can arrive
        # twice. Keying the run by correlation is not enough - a re-delivery
        # after the first run terminated (lock released) would start a SECOND
        # run and re-execute. Return the existing run for a correlation we have
        # already dispatched, so a duplicate verdict is a no-op (defense in
        # depth with the event idempotency_key dedup at ingress).
        idempotency_key = str(verdict.get("idempotency_key") or correlation)
        existing_by_corr = self.action_runs.get(correlation)
        if existing_by_corr is not None:
            if existing_by_corr.idempotency_key != idempotency_key:
                self.record_behavior("dispatch:correlation_reuse_rejected")
                raise ValueError("ActionRun correlation cannot be reused by another generation")
            self.record_behavior("dispatch:duplicate")
            if existing_by_corr.state not in _TERMINAL_STATES:
                await self._resume_rehydrated(existing_by_corr)
            elif not existing_by_corr.terminal_published:
                await self._emit_action_run(existing_by_corr)
                await self._finalize_terminal_replay(existing_by_corr)
            else:
                await self._finalize_terminal_replay(existing_by_corr)
            return existing_by_corr
        existing_by_idempotency = self._idempotency_runs.get(idempotency_key)
        if existing_by_idempotency is not None:
            self.record_behavior("dispatch:idempotent_duplicate")
            return existing_by_idempotency

        # Per-resource mutex: refuse to start a new run while another is
        # active on the same resource. Second dispatcher waits for the
        # first to terminate before starting.
        if resource_id and resource_id in self._resource_locks:
            existing = self._find_active_run(str(resource_id))
            if existing is not None:
                self.record_behavior("dispatch:lock_contention")
                raise RuntimeError("resource already has an active ActionRun")
            retained = next(
                (
                    run
                    for run in self.action_runs.values()
                    if run.resource_id == str(resource_id) and run.state in _TERMINAL_STATES
                ),
                None,
            )
            if retained is not None:
                self.record_behavior("dispatch:terminal_fence")
                if retained.terminal_published:
                    await self._finalize_terminal_replay(retained)
                else:
                    await self._emit_action_run(retained)
                    await self._finalize_terminal_replay(retained)
            else:
                raise RuntimeError("resource mutation fence has no recoverable ActionRun")

        # Degrade to shadow when hard dependencies are missing.
        shadow_mode = (
            resolved_autonomy_ceiling is Autonomy.SHADOW_ONLY
            or self._must_shadow()
            or not (self._saga_available and self._vidar_available)
        )

        # Propagate the approval quorum the judge set (2 for irreversible
        # actions, agent-pantheon.md 4.6). Floor at 1 so a forged / malformed
        # verdict can never yield a zero-or-negative quorum that would let an
        # action execute with no approver; Thor MUST NOT hard-code 1 and drop
        # the judge's two-approver requirement.
        quorum_required = max(1, int(verdict.get("quorum_required", 1)))
        run = ActionRun(
            correlation_id=correlation,
            action_type=action_type,
            resource_id=resource_id,
            state=ActionRunState.VERDICTED,
            verdict=risk_verdict,
            action_id=action_run_lineage.optional_bounded_text(
                verdict.get("action_id"),
                field_name="action_id",
            ),
            idempotency_key=str(verdict.get("idempotency_key") or correlation),
            params=params,
            shadow_mode=shadow_mode,
            resolved_autonomy_ceiling=resolved_autonomy_ceiling,
            quorum_required=quorum_required,
            initiator_principal=verdict.get("initiator_principal"),
            rollback_contract=str(verdict.get("rollback_contract", "state_forward_only")),
            decision_case=decision_case,
            operational_context=operational_context,
            test_context_guard=(
                TestContextDispatchBinding.model_validate(verdict["test_context_guard"])
                if verdict.get("test_context_guard") is not None
                else None
            ),
            workflow_action=action_run_lineage.bounded_workflow_action(
                verdict.get("workflow_action")
            ),
            kinetic_proposal=(
                kinetic_proposal.model_dump(mode="json") if kinetic_proposal is not None else None
            ),
            prospective_lineage=(
                prospective_lineage.model_dump(mode="json")
                if prospective_lineage is not None
                else None
            ),
            approval_expires_at=(
                self._now() + timedelta(seconds=self._hil_timeout_seconds)
                if risk_verdict == "hil"
                else None
            ),
        )
        claim_status, existing = await resolve_correlation_claim(self._state_store, run)
        if claim_status in {"execution_completed", "correlation_completed"}:
            run.transition(ActionRunState.DENY_DROPPED)
            run.outcome = (
                "duplicate_execution_already_completed"
                if claim_status == "execution_completed"
                else "duplicate_correlation_already_completed"
            )
            self.action_runs[correlation] = run
            self._idempotency_runs[run.idempotency_key] = run
            await self._emit_action_run(run)
            self.record_behavior("dispatch:completed_duplicate")
            return run
        if claim_status == "contended":
            raise _ExecutionResourceUnavailableError
        if claim_status == "active":
            if existing is None:
                raise RuntimeError("Thor active correlation has no ActionRun")
            self.record_behavior("dispatch:idempotent_duplicate")
            return existing
        self.action_runs[correlation] = run
        self._idempotency_runs[run.idempotency_key] = run
        if resource_id:
            self._resource_locks.add(str(resource_id))
        try:
            if risk_verdict == "auto" and not shadow_mode:
                if not await self._claim_execution_resource(run):
                    run.transition(ActionRunState.DENY_DROPPED)
                    run.outcome = "duplicate_execution_already_completed"
                    await self._emit_action_run(run)
                    self._release_lock(resource_id)
                    return run
            # Emit the initial VERDICTED state so downstream consumers
            # (audit chain, Var) see the lifecycle start.
            await self._emit_action_run(run)
            # Record the verdict split so scenario checks can prove shadow and
            # deny paths never mutate.
            self.record_behavior(f"dispatch:{risk_verdict}")
            if shadow_mode:
                self.record_behavior("dispatch:shadow")
                # Distinguish a policy shadow (forced) from a degraded shadow (a
                # hard dependency - Saga/Vidar - is down), so a scenario can see
                # a safety-relevant degradation, not just "shadow".
                if not (self._saga_available and self._vidar_available):
                    self.record_behavior("dispatch:degraded")

            if risk_verdict == "deny":
                run.transition(ActionRunState.DENY_DROPPED)
                await self._emit_action_run(run)
                self._release_lock(resource_id)
                return run

            if risk_verdict == "hil":
                run.transition(ActionRunState.HIL_PENDING)
                await self._emit_action_run(run)
                # Lock is held intentionally across the HIL wait; released
                # when _execute (on approval) or the reject path terminates.
                return run

            # auto path (releases the lock via _execute's own finally)
            await self._execute(run)
            return run
        except Exception:
            # Fail-safe: a lifecycle emit (bus hiccup) MUST NOT leave the
            # resource locked forever - that would deadlock every future
            # action on it (permanent dispatch:lock_contention). Release and
            # re-raise. The HIL path returns normally, so its intentional lock
            # hold is unaffected by this guard.
            self.record_behavior("dispatch:publication_failed")
            if run.state is ActionRunState.VERDICTED and not run.resource_claimed:
                self.action_runs.pop(run.correlation_id, None)
                if self._idempotency_runs.get(run.idempotency_key) is run:
                    self._idempotency_runs.pop(run.idempotency_key, None)
                self._release_lock(resource_id)
            raise

    async def _execute(self, run: ActionRun) -> None:
        await thor_execution.execute(self, run)

    async def _invoke_executor(self, run: ActionRun) -> bool:
        return await thor_execution.invoke_executor(self, run)

    async def _claim_execution_resource(self, run: ActionRun) -> bool:
        return await thor_execution.claim_execution_resource(self, run)

    async def _handle_approval(self, approval: dict[str, Any]) -> None:
        correlation = str(approval.get("correlation_id", ""))
        lock = self._correlation_locks.setdefault(correlation, _ReentrantAsyncLock())
        async with lock:
            await self._handle_approval_locked(approval, correlation=correlation)

    async def _handle_approval_locked(
        self,
        approval: dict[str, Any],
        *,
        correlation: str,
    ) -> None:
        run = self.action_runs.get(correlation)
        if run is None:
            return
        if not approval_matches_action_run(approval, run.to_dict()):
            self.record_behavior("approval:identity_mismatch")
            raise ValueError("approval identity does not match the current ActionRun")
        # Idempotency: only a run still awaiting its HIL decision may act on an
        # approval. At-least-once delivery can redeliver the same object.approval
        # (or a duplicate can arrive), and without this guard an approval for a
        # run already approved / executing / terminal would re-enter _execute -
        # double-executing a completed mutation via the privileged executor, or
        # re-running rollback. dispatch_verdict has its own idempotency guard;
        # this is the matching one for the approval path.
        if run.state != ActionRunState.HIL_PENDING:
            self.record_behavior("approval:duplicate")
            if run.state is ActionRunState.APPROVED:
                await self._execute(run)
                return
            if run.state in _TERMINAL_STATES and not run.terminal_published:
                await self._emit_action_run(run)
                await self._finalize_terminal_replay(run)
            elif run.state in _TERMINAL_STATES:
                await self._finalize_terminal_replay(run)
            return
        if run.approval_expires_at is None or self._now() >= run.approval_expires_at:
            await self._expire_approval(run)
            return
        if approval.get("state") == "approved":
            run.transition(ActionRunState.APPROVED)
            await self._execute(run)
        else:
            if not run.resource_claimed and not await self._claim_execution_resource(run):
                run.transition(ActionRunState.DENY_DROPPED)
                run.outcome = "duplicate_execution_already_completed"
                await self._emit_action_run(run)
                self._release_lock(run.resource_id)
                return
            try:
                run.transition(ActionRunState.REJECTED)
                await self._emit_action_run(run)
                await self._release_resource_claim(run)
            finally:
                self._release_lock(run.resource_id)

    async def expire_pending_approvals(self) -> int:
        """Expire HIL runs whose bounded approval window has elapsed."""

        expired = [
            run
            for run in self.action_runs.values()
            if run.state is ActionRunState.HIL_PENDING
            and (run.approval_expires_at is None or self._now() >= run.approval_expires_at)
        ]
        for run in expired:
            lock = self._correlation_locks.setdefault(
                run.correlation_id,
                _ReentrantAsyncLock(),
            )
            async with lock:
                if run.state is ActionRunState.HIL_PENDING and (
                    run.approval_expires_at is None or self._now() >= run.approval_expires_at
                ):
                    await self._expire_approval(run)
        return len(expired)

    async def _expire_approval(self, run: ActionRun) -> None:
        if not run.resource_claimed and not await self._claim_execution_resource(run):
            run.transition(ActionRunState.DENY_DROPPED)
            run.outcome = "duplicate_execution_already_completed"
            await self._emit_action_run(run)
            self._release_lock(run.resource_id)
            return
        try:
            run.transition(ActionRunState.REJECTED)
            run.outcome = "approval_expired"
            await self._emit_action_run(run)
            await self._release_resource_claim(run)
            self.record_behavior("approval:expired")
        finally:
            self._release_lock(run.resource_id)

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise RuntimeError("Thor clock MUST be timezone-aware")
        return now.astimezone(UTC)

    async def _handle_rollback(self, rollback: dict[str, Any]) -> None:
        correlation = str(rollback.get("correlation_id", ""))
        lock = self._correlation_locks.setdefault(correlation, _ReentrantAsyncLock())
        async with lock:
            await self._handle_rollback_locked(rollback, correlation=correlation)

    async def _handle_rollback_locked(
        self,
        rollback: dict[str, Any],
        *,
        correlation: str,
    ) -> None:
        run = self.action_runs.get(correlation)
        if run is not None and not rollback_matches_action_run(rollback, run.to_dict()):
            self.record_behavior("rollback:identity_mismatch")
            return
        rollback_ref = bounded_rollback_ref(rollback.get("rollback_ref"))
        succeeded = rollback.get("state") == "succeeded" and rollback_ref is not None
        if run is not None and run.state is ActionRunState.ROLLBACK_FAILED and succeeded:
            run.rollback_ref = rollback_ref
            run.outcome = "rollback_succeeded"
            run.transition(ActionRunState.ROLLED_BACK)
            await self._emit_action_run(run)
            await self._release_resource_claim(run)
            self._release_lock(run.resource_id)
            return
        if run is not None and run.state in _TERMINAL_STATES:
            if run.terminal_published:
                await self._finalize_terminal_replay(run)
            else:
                await self._emit_action_run(run)
                await self._finalize_terminal_replay(run)
            return
        if run is None or run.state not in {
            ActionRunState.FAILED,
            ActionRunState.EXECUTION_UNKNOWN,
        }:
            return
        run.rollback_ref = rollback_ref if succeeded else None
        run.outcome = "rollback_succeeded" if succeeded else "rollback_failed"
        run.transition(ActionRunState.ROLLED_BACK if succeeded else ActionRunState.ROLLBACK_FAILED)
        await self._emit_action_run(run)
        self.record_behavior(run.outcome)
        if succeeded:
            await self._release_resource_claim(run)
            self._release_lock(run.resource_id)

    # ---- helpers -------------------------------------------------------

    def _release_lock(self, resource_id: Any) -> None:
        thor_persistence.release_lock(self, resource_id)

    def _evict_terminal_overflow(self) -> None:
        thor_persistence.evict_terminal_overflow(self)

    def _find_active_run(self, resource_id: str) -> ActionRun | None:
        return thor_persistence.find_active_run(self, resource_id)

    async def _emit_action_run(self, run: ActionRun) -> None:
        await thor_persistence.emit_action_run(self, run)

    async def _delete_terminal_state(self, run: ActionRun) -> None:
        await thor_persistence.delete_terminal_state(self, run)

    async def _finalize_terminal_replay(self, run: ActionRun) -> None:
        await thor_persistence.finalize_terminal_replay(self, run)

    async def _release_resource_claim(self, run: ActionRun) -> None:
        await thor_persistence.release_resource_claim(self, run)

    # ---- conversational port -------------------------------------------

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        return thor_introspection.evidence_available(self.action_runs)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        return thor_introspection.introspect(
            spec=self.spec,
            runs=self.action_runs,
            shadow_forced=self._shadow_by_default,
            question=question,
            context=context,
        )


async def _default_executor(context: dict[str, Any]) -> bool:
    """Default executor for tests: always succeed. Fork overrides."""
    return True


__all__ = [
    "Thor",
    "ActionRun",
    "ActionRunState",
    "ActionExecutor",
    "ActionRunStore",
    "ExecutionAuditRecorder",
]
