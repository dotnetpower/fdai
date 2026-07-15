"""Tool-call dispatch executor - the core glue for the ``tool_call`` path.

Sibling of :class:`~fdai.core.executor.executor.ShadowExecutor` and
:class:`~fdai.core.executor.direct_api.DirectApiShadowExecutor`. Where
those open a remediation PR / mutate a substrate, this executor invokes a
**registered tool** (a function: generate a PDF, send a notification,
open a ticket) from the "Tool call" section of
``docs/roadmap/decisioning/execution-model.md`` via
:class:`~fdai.shared.providers.tool.ToolExecutor`.

Same safety-invariant discipline; different delivery surface:

- P1 shadow-only - an ``Action`` with :attr:`Mode.ENFORCE` is refused
  BEFORE the per-target lock.
- Fail-closed on missing invariants (stop_condition, rollback,
  blast_radius, citing_rules).
- Per-target lock serialises concurrent actions on the same tool target
  so a re-delivery cannot double-run a tool mid-flight.
- Blast-radius cap identical to
  :class:`~fdai.core.executor.executor.ExecutorConfig` (a tool can still
  fan out - e.g. one report per resource - so the cap still applies).
- Idempotency-by-key at two layers: in-process ``_dedupe`` cache (fast
  path) + the adapter's own ledger (authoritative; returns
  :attr:`ToolCallOutcome.ALREADY_APPLIED`).

Every terminal path writes exactly one audit entry with
``action_kind = "executor.tool_call.<outcome>"`` so the audit trail is
distinguishable from the PR-native and direct-API paths.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fdai.core.executor.executor import (
    ExecutorConfig,
    _missing_safety_invariant,
)
from fdai.shared.contracts.models import Action, Mode
from fdai.shared.providers.idempotency import IdempotencyStore
from fdai.shared.providers.resource_lock import ResourceLock
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.tool import (
    ToolCallOutcome,
    ToolCallReceipt,
    ToolCallRequest,
    ToolError,
    ToolExecutor,
    ToolPreconditionError,
    ToolPromotionError,
)

_LOG = logging.getLogger(__name__)

ToolReceiptObserver = Callable[[ToolCallRequest, ToolCallReceipt], Awaitable[None]]


class ToolCallExecutionOutcome(StrEnum):
    """Terminal outcome for one :meth:`ToolCallShadowExecutor.execute` call.

    Deliberately distinct from
    :class:`~fdai.core.executor.executor.ExecutorOutcome` and
    :class:`~fdai.core.executor.direct_api.DirectApiExecutionOutcome` so a
    path-specific audit consumer does not accidentally match a tool-call
    record; the three paths share only the ``ExecutionResult``-shaped
    audit context.
    """

    DISPATCHED = "dispatched"
    """The tool ran (adapter returned :attr:`ToolCallOutcome.SUCCEEDED`)."""

    ALREADY_APPLIED = "already_applied"
    """Duplicate delivery: the adapter's idempotency ledger (or the
    executor's in-process dedupe) returned a prior receipt."""

    ABSTAINED_BLAST_RADIUS = "abstained_blast_radius"
    """Blast-radius count / rate exceeded the executor cap; escalate to
    HIL rather than partial-run."""

    ABSTAINED_PRECONDITION = "abstained_precondition"
    """An ActionType ``precondition`` did not hold at dispatch time
    (adapter raised :class:`ToolPreconditionError`). Tool not invoked."""

    STOPPED = "stopped"
    """A ``stop_condition`` fired mid-flight (adapter returned
    :attr:`ToolCallOutcome.STOPPED`). The adapter attempted a rollback;
    :attr:`ToolCallExecutionResult.rollback_succeeded` records it."""

    FAILED = "failed"
    """The tool raised or the adapter returned
    :attr:`ToolCallOutcome.FAILED`. Rollback (if any) is recorded on
    :attr:`ToolCallExecutionResult.rollback_succeeded`."""

    REJECTED_MODE = "rejected_mode"
    """Action carried :attr:`Mode.ENFORCE` but the P1 executor is
    shadow-only OR the adapter refused an enforce dispatch that lacked
    the promotion label."""

    REJECTED_INVARIANT = "rejected_invariant"
    """Action was missing one of the four safety invariants (empty
    ``stop_condition``, missing ``rollback_ref.kind``, missing
    ``blast_radius``, missing ``citing_rules``)."""


@dataclass(frozen=True, slots=True)
class ToolCallExecutionResult:
    """Outcome of one :meth:`ToolCallShadowExecutor.execute` call."""

    action_id: str
    outcome: ToolCallExecutionOutcome
    mode: Mode = Mode.SHADOW
    receipt_ref: str | None = None
    rollback_succeeded: bool | None = None
    reason: str | None = None
    audit_context: dict[str, Any] = field(default_factory=dict)


# Outcomes that ran the tool (or returned a prior receipt for one). Only
# these are recorded in the durable idempotency store.
_TC_RAN_OUTCOMES: frozenset[ToolCallExecutionOutcome] = frozenset(
    {
        ToolCallExecutionOutcome.DISPATCHED,
        ToolCallExecutionOutcome.ALREADY_APPLIED,
    }
)


def _tc_result_to_payload(result: ToolCallExecutionResult) -> dict[str, Any]:
    return {
        "action_id": result.action_id,
        "outcome": result.outcome.value,
        "mode": result.mode.value,
        "receipt_ref": result.receipt_ref,
        "rollback_succeeded": result.rollback_succeeded,
        "reason": result.reason,
        "audit_context": dict(result.audit_context),
    }


def _tc_result_from_payload(payload: Mapping[str, Any]) -> ToolCallExecutionResult:
    ctx = payload.get("audit_context") or {}
    rollback = payload.get("rollback_succeeded")
    return ToolCallExecutionResult(
        action_id=str(payload["action_id"]),
        outcome=ToolCallExecutionOutcome(str(payload["outcome"])),
        mode=Mode(str(payload.get("mode", Mode.SHADOW.value))),
        receipt_ref=None if payload.get("receipt_ref") is None else str(payload["receipt_ref"]),
        rollback_succeeded=rollback if isinstance(rollback, bool) else None,
        reason=None if payload.get("reason") is None else str(payload["reason"]),
        audit_context=dict(ctx) if isinstance(ctx, Mapping) else {},
    )


class ToolCallShadowExecutor:
    """The dispatch surface for the ``tool_call`` execution path (P1)."""

    def __init__(
        self,
        *,
        executor: ToolExecutor,
        audit_store: StateStore,
        resource_lock: ResourceLock,
        config: ExecutorConfig | None = None,
        idempotency: IdempotencyStore | None = None,
        receipt_observer: ToolReceiptObserver | None = None,
        enforce: bool = False,
    ) -> None:
        self._executor = executor
        self._audit_store = audit_store
        self._resource_lock = resource_lock
        self._config = config or ExecutorConfig()
        self._idempotency = idempotency
        self._receipt_observer = receipt_observer
        self._enforce = enforce
        # idempotency_key -> ToolCallExecutionResult. Same FIFO-bounded
        # policy as :class:`ShadowExecutor` so a long-running control
        # loop cannot grow unbounded memory on distinct events. The
        # durable dedup source is the audit_log UNIQUE constraint.
        self._dedupe: dict[str, ToolCallExecutionResult] = {}

    async def execute(self, *, action: Action) -> ToolCallExecutionResult:
        """Dispatch one action to its registered tool; always audits.

        Returns a :class:`ToolCallExecutionResult` describing the terminal
        state. Never raises for a business-logic failure - a broken
        precondition, a blast-radius overrun, or an enforce-mode action
        all fail closed into an audited abstain / refusal, matching the
        "fail toward safety" rule in
        ``architecture.instructions.md § Design Principles``.
        """

        # Shadow-only path (P1) - reject enforce-mode Actions BEFORE the
        # lock. The adapter would also raise ToolPromotionError but this
        # saves a per-target lock cycle on a pure refusal.
        if action.mode is not Mode.SHADOW and not self._enforce:
            return await self._finish(
                action=action,
                outcome=ToolCallExecutionOutcome.REJECTED_MODE,
                reason=(
                    "enforce mode is out of scope in P1 (execution-model.md 5.6 promotion contract)"
                ),
            )

        invariant_reason = _missing_safety_invariant(action)
        if invariant_reason is not None:
            return await self._finish(
                action=action,
                outcome=ToolCallExecutionOutcome.REJECTED_INVARIANT,
                reason=invariant_reason,
            )

        # In-process dedupe (fast path) - the adapter's ledger is the
        # authoritative check inside the lock, but a re-delivery this
        # process already saw short-circuits without acquiring the lock.
        cached = self._dedupe.get(action.idempotency_key)
        if cached is not None:
            return cached

        async with self._resource_lock.acquire(action.target_resource_ref):
            cached = self._dedupe.get(action.idempotency_key)
            if cached is not None:
                return cached

            # Durable L2 guard - a tool run recorded under this key
            # (possibly before a restart) short-circuits the invocation.
            if self._idempotency is not None:
                stored = await self._idempotency.seen(action.idempotency_key)
                if stored is not None:
                    result = _tc_result_from_payload(stored)
                    self._remember(action.idempotency_key, result)
                    return result

            blast_reason = self._check_blast_radius(action)
            if blast_reason is not None:
                return await self._finish(
                    action=action,
                    outcome=ToolCallExecutionOutcome.ABSTAINED_BLAST_RADIUS,
                    reason=blast_reason,
                )

            request = _build_tool_call_request(action)
            try:
                receipt = await self._executor.execute(request)
            except ToolPromotionError as exc:
                return await self._finish(
                    action=action,
                    outcome=ToolCallExecutionOutcome.REJECTED_MODE,
                    reason=f"adapter refused promotion: {exc}",
                )
            except ToolPreconditionError as exc:
                return await self._finish(
                    action=action,
                    outcome=ToolCallExecutionOutcome.ABSTAINED_PRECONDITION,
                    reason=str(exc),
                )
            except ToolError as exc:
                return await self._finish(
                    action=action,
                    outcome=ToolCallExecutionOutcome.FAILED,
                    reason=f"adapter error [{exc.kind}]: {exc}",
                    rollback_succeeded=False,
                    remember=False,
                )
            except asyncio.CancelledError:
                await self._finish(
                    action=action,
                    outcome=ToolCallExecutionOutcome.FAILED,
                    reason="tool-call execution cancelled",
                    rollback_succeeded=False,
                    remember=False,
                )
                raise
            except Exception as exc:  # noqa: BLE001 - executor boundary
                # Uncontrolled adapter failure: fail closed. Log via the
                # module logger so an operator can investigate, then audit
                # the failure with rollback_succeeded=False so an on-call
                # sees the manual-rollback flag.
                _LOG.exception("tool-call adapter raised uncontrolled")
                return await self._finish(
                    action=action,
                    outcome=ToolCallExecutionOutcome.FAILED,
                    reason=f"uncontrolled adapter error: {exc!r}",
                    rollback_succeeded=False,
                    remember=False,
                )

            if (
                self._receipt_observer is not None
                and receipt.outcome
                in {ToolCallOutcome.SUCCEEDED, ToolCallOutcome.ALREADY_APPLIED}
            ):
                try:
                    await self._receipt_observer(request, receipt)
                except Exception as exc:  # noqa: BLE001 - linkage boundary
                    _LOG.exception("tool-call receipt observer failed")
                    return await self._finish(
                        action=action,
                        outcome=ToolCallExecutionOutcome.FAILED,
                        reason=f"receipt observer error: {type(exc).__name__}",
                        receipt_ref=receipt.receipt_ref,
                        rollback_succeeded=False,
                        remember=False,
                    )
            return await self._finish_from_receipt(action=action, receipt=receipt)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _check_blast_radius(self, action: Action) -> str | None:
        count = action.blast_radius.count
        if count is not None and count > self._config.max_affected_resources:
            return (
                f"blast-radius count {count} exceeds executor cap "
                f"{self._config.max_affected_resources}"
            )
        rpm = action.blast_radius.rate_per_minute
        if rpm is not None and rpm > self._config.max_rate_per_minute:
            return (
                f"blast-radius rate {rpm}/min exceeds executor cap "
                f"{self._config.max_rate_per_minute}/min"
            )
        return None

    async def _finish_from_receipt(
        self, *, action: Action, receipt: ToolCallReceipt
    ) -> ToolCallExecutionResult:
        """Map an adapter :class:`ToolCallReceipt` -> executor outcome + audit."""

        mapping: dict[ToolCallOutcome, ToolCallExecutionOutcome] = {
            ToolCallOutcome.SUCCEEDED: ToolCallExecutionOutcome.DISPATCHED,
            ToolCallOutcome.ALREADY_APPLIED: ToolCallExecutionOutcome.ALREADY_APPLIED,
            ToolCallOutcome.PRECONDITION_FAILED: (ToolCallExecutionOutcome.ABSTAINED_PRECONDITION),
            ToolCallOutcome.STOPPED: ToolCallExecutionOutcome.STOPPED,
            ToolCallOutcome.FAILED: ToolCallExecutionOutcome.FAILED,
        }
        outcome = mapping[receipt.outcome]
        return await self._finish(
            action=action,
            outcome=outcome,
            reason=receipt.detail,
            receipt_ref=receipt.receipt_ref,
            rollback_succeeded=receipt.rollback_succeeded,
            remember=receipt.outcome is not ToolCallOutcome.FAILED,
        )

    async def _finish(
        self,
        *,
        action: Action,
        outcome: ToolCallExecutionOutcome,
        reason: str | None,
        receipt_ref: str | None = None,
        rollback_succeeded: bool | None = None,
        remember: bool = True,
    ) -> ToolCallExecutionResult:
        result = ToolCallExecutionResult(
            action_id=str(action.action_id),
            outcome=outcome,
            mode=action.mode,
            receipt_ref=receipt_ref,
            rollback_succeeded=rollback_succeeded,
            reason=reason,
            audit_context={
                "tool_ref": action.target_resource_ref,
                "action_type": action.action_type,
                "operation": action.operation.value,
                "blast_radius_scope": action.blast_radius.scope.value,
            },
        )
        # Cache non-degenerate outcomes so a retry does not re-hit the
        # adapter for the same key. Rejections (mode/invariant) are also
        # cached because they are stable properties of the Action itself.
        # Order matters: audit write MUST land before we populate the
        # cache, otherwise a raise from :meth:`_write_audit` would leave a
        # cached "already handled" hit that silently suppresses the audit
        # trail on the retry.
        await self._write_audit(action=action, result=result)
        # Durable dedup: record only outcomes that ran the tool so a
        # post-restart retry does not re-run it.
        if self._idempotency is not None and outcome in _TC_RAN_OUTCOMES:
            await self._idempotency.record(action.idempotency_key, _tc_result_to_payload(result))
        if remember:
            self._remember(action.idempotency_key, result)
        return result

    def _remember(self, key: str, result: ToolCallExecutionResult) -> None:
        """FIFO-bounded insert. Mirrors :meth:`ShadowExecutor._remember`."""
        cap = max(1, self._config.max_dedupe_entries)
        if key in self._dedupe:
            del self._dedupe[key]
        elif len(self._dedupe) >= cap:
            self._dedupe.pop(next(iter(self._dedupe)))
        self._dedupe[key] = result

    async def _write_audit(self, *, action: Action, result: ToolCallExecutionResult) -> None:
        entry = {
            "event_id": str(action.event_id),
            "action_id": str(action.action_id),
            "idempotency_key": action.idempotency_key,
            "actor": "fdai.core.executor.tool_call",
            "action_kind": f"executor.tool_call.{result.outcome.value}",
            "mode": action.mode.value,
            "execution_path": "tool_call",
            "citing_rule_ids": list(action.citing_rules),
            "outcome": result.outcome.value,
            "receipt_ref": result.receipt_ref,
            "rollback_succeeded": result.rollback_succeeded,
            "reason": result.reason,
            "tool_ref": action.target_resource_ref,
            "operation": action.operation.value,
            "rollback_kind": action.rollback_ref.kind.value,
            "rollback_reference": action.rollback_ref.reference,
            "stop_condition": action.stop_condition,
            "blast_radius": {
                "scope": action.blast_radius.scope.value,
                "count": action.blast_radius.count,
                "rate_per_minute": action.blast_radius.rate_per_minute,
            },
            "recorded_at": datetime.now(tz=UTC).isoformat(),
        }
        await self._audit_store.append_audit_entry(entry)


def _build_tool_call_request(action: Action) -> ToolCallRequest:
    """Assemble a :class:`ToolCallRequest` from one :class:`Action`.

    The adapter's ``arguments`` block is the ActionType's rendered param
    bundle (already scalar per the ActionBuilder contract); the executor
    never assembles tool-specific payloads itself.
    """
    return ToolCallRequest(
        action_id=action.action_id,
        idempotency_key=action.idempotency_key,
        action_type_name=action.action_type,
        rule_ids=tuple(action.citing_rules),
        tool_ref=action.target_resource_ref,
        arguments=dict(action.params),
        labels=(("enforce",) if action.mode is Mode.ENFORCE else ("shadow",)),
        mode=action.mode,
    )


__all__ = [
    "ToolReceiptObserver",
    "ToolCallExecutionOutcome",
    "ToolCallExecutionResult",
    "ToolCallShadowExecutor",
]
