"""Direct-API dispatch executor - the core glue for W2.3.

Sibling of :class:`~fdai.core.executor.executor.ShadowExecutor`.
Where ``ShadowExecutor`` opens remediation PRs via
:class:`~fdai.shared.providers.remediation_pr.RemediationPrPublisher`,
this executor dispatches the ``direct_api`` execution path from
the "Direct API" section of ``docs/roadmap/decisioning/execution-model.md``
via :class:`~fdai.shared.providers.direct_api.DirectApiExecutor`.

Same safety-invariant discipline; different delivery surface:

- P1 shadow-only - an ``Action`` with :attr:`Mode.ENFORCE` is refused
  BEFORE the per-resource lock.
- Fail-closed on missing invariants (stop_condition, rollback,
  blast_radius, citing_rules).
- Per-resource lock serialises concurrent actions on the same
  substrate resource so a re-delivery cannot double-apply mid-flight.
- Blast-radius cap identical to
  :class:`~fdai.core.executor.executor.ExecutorConfig`.
- Idempotency-by-key at two layers: in-process ``_dedupe`` cache (fast
  path) + the adapter's own ledger (authoritative; returns
  :attr:`DirectApiOutcome.ALREADY_APPLIED`).

Every terminal path writes exactly one audit entry with
``action_kind = "executor.direct_api.<outcome>"`` so the audit trail is
distinguishable from the PR-native path.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fdai.core.executor.executor import (
    ExecutorConfig,
    _idempotency_lock_key,
    _missing_safety_invariant,
    _resource_lock_key,
)
from fdai.shared.contracts.models import Action, Mode
from fdai.shared.providers.direct_api import (
    DirectApiError,
    DirectApiExecutor,
    DirectApiOutcome,
    DirectApiPreconditionError,
    DirectApiPromotionError,
    DirectApiReceipt,
    DirectApiRequest,
)
from fdai.shared.providers.idempotency import IdempotencyStore
from fdai.shared.providers.resource_lock import ResourceLock
from fdai.shared.providers.state_store import StateStore

_LOG = logging.getLogger(__name__)


class DirectApiExecutionOutcome(StrEnum):
    """Terminal outcome for one :meth:`DirectApiShadowExecutor.execute` call.

    Deliberately distinct from
    :class:`~fdai.core.executor.executor.ExecutorOutcome` so a PR-
    path audit consumer that filters on those values does not
    accidentally match a direct-API record; the two paths share only the
    ``ExecutionResult``-shaped audit context.
    """

    DISPATCHED = "dispatched"
    """The substrate call succeeded (adapter returned
    :attr:`DirectApiOutcome.SUCCEEDED`)."""

    ALREADY_APPLIED = "already_applied"
    """Duplicate delivery: the adapter's idempotency ledger (or the
    executor's in-process dedupe) returned a prior receipt."""

    ABSTAINED_BLAST_RADIUS = "abstained_blast_radius"
    """Blast-radius count / rate exceeded the executor cap; escalate to
    HIL rather than partial-apply."""

    ABSTAINED_PRECONDITION = "abstained_precondition"
    """An ActionType ``precondition`` did not hold at dispatch time
    (adapter raised :class:`DirectApiPreconditionError`). No mutation
    attempted."""

    STOPPED = "stopped"
    """A ``stop_condition`` fired mid-flight (adapter returned
    :attr:`DirectApiOutcome.STOPPED`). The adapter attempted a rollback;
    :attr:`DirectApiExecutionResult.rollback_succeeded` records the
    outcome."""

    FAILED = "failed"
    """The substrate call raised or the adapter returned
    :attr:`DirectApiOutcome.FAILED`. Rollback (if any) is recorded on
    :attr:`DirectApiExecutionResult.rollback_succeeded`."""

    REJECTED_MODE = "rejected_mode"
    """Action carried :attr:`Mode.ENFORCE` but the P1 executor is
    shadow-only OR the adapter refused an enforce dispatch that lacked
    the promotion label."""

    REJECTED_INVARIANT = "rejected_invariant"
    """Action was missing one of the four safety invariants (empty
    ``stop_condition``, missing ``rollback_ref.kind``, missing
    ``blast_radius``, missing ``citing_rules``)."""

    REJECTED_IDEMPOTENCY_CONFLICT = "rejected_idempotency_conflict"
    """The idempotency key was already bound to a different action."""


@dataclass(frozen=True, slots=True)
class DirectApiExecutionResult:
    """Outcome of one :meth:`DirectApiShadowExecutor.execute` call."""

    action_id: str
    outcome: DirectApiExecutionOutcome
    mode: Mode = Mode.SHADOW
    receipt_ref: str | None = None
    rollback_succeeded: bool | None = None
    reason: str | None = None
    audit_context: dict[str, Any] = field(default_factory=dict)


# Outcomes that hit the substrate (a mutation, or a prior receipt for
# one). Only these are recorded in the durable idempotency store.
_DA_MUTATION_OUTCOMES: frozenset[DirectApiExecutionOutcome] = frozenset(
    {
        DirectApiExecutionOutcome.DISPATCHED,
        DirectApiExecutionOutcome.ALREADY_APPLIED,
    }
)


def _da_result_to_payload(result: DirectApiExecutionResult) -> dict[str, Any]:
    return {
        "action_id": result.action_id,
        "outcome": result.outcome.value,
        "mode": result.mode.value,
        "receipt_ref": result.receipt_ref,
        "rollback_succeeded": result.rollback_succeeded,
        "reason": result.reason,
        "audit_context": dict(result.audit_context),
    }


def _da_result_from_payload(payload: Mapping[str, Any]) -> DirectApiExecutionResult:
    ctx = payload.get("audit_context") or {}
    rollback = payload.get("rollback_succeeded")
    return DirectApiExecutionResult(
        action_id=str(payload["action_id"]),
        outcome=DirectApiExecutionOutcome(str(payload["outcome"])),
        mode=Mode(str(payload.get("mode", Mode.SHADOW.value))),
        receipt_ref=None if payload.get("receipt_ref") is None else str(payload["receipt_ref"]),
        rollback_succeeded=rollback if isinstance(rollback, bool) else None,
        reason=None if payload.get("reason") is None else str(payload["reason"]),
        audit_context=dict(ctx) if isinstance(ctx, Mapping) else {},
    )


def _direct_api_fingerprint(action: Action) -> str:
    canonical = json.dumps(
        action.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DirectApiShadowExecutor:
    """The dispatch surface for the ``direct_api`` execution path (P1)."""

    def __init__(
        self,
        *,
        executor: DirectApiExecutor,
        audit_store: StateStore,
        resource_lock: ResourceLock,
        config: ExecutorConfig | None = None,
        idempotency: IdempotencyStore | None = None,
    ) -> None:
        self._executor = executor
        self._audit_store = audit_store
        self._resource_lock = resource_lock
        self._config = config or ExecutorConfig()
        self._idempotency = idempotency
        # idempotency_key -> DirectApiExecutionResult. Same FIFO-bounded
        # policy as :class:`ShadowExecutor` so a long-running control
        # loop cannot grow unbounded memory on distinct events. The
        # durable dedup source is the audit_log UNIQUE constraint.
        self._dedupe: dict[str, DirectApiExecutionResult] = {}

    async def execute(self, *, action: Action) -> DirectApiExecutionResult:
        """Dispatch one action via the substrate API; always audits.

        Returns a :class:`DirectApiExecutionResult` describing the
        terminal state. Never raises for a business-logic failure - a
        broken precondition, a blast-radius overrun, or an enforce-mode
        action all fail closed into an audited abstain / refusal,
        matching the "fail toward safety" rule in
        ``architecture.instructions.md § Design Principles``.
        """

        # Shadow-only path (P1) - reject enforce-mode Actions BEFORE the
        # lock. The adapter would also raise DirectApiPromotionError but
        # this saves a per-resource lock cycle on a pure refusal.
        if action.mode is not Mode.SHADOW:
            return await self._finish(
                action=action,
                outcome=DirectApiExecutionOutcome.REJECTED_MODE,
                reason=(
                    "enforce mode is out of scope in P1 (execution-model.md 5.2 promotion contract)"
                ),
            )

        invariant_reason = _missing_safety_invariant(action)
        if invariant_reason is not None:
            return await self._finish(
                action=action,
                outcome=DirectApiExecutionOutcome.REJECTED_INVARIANT,
                reason=invariant_reason,
            )

        # In-process dedupe (fast path) - the adapter's ledger is the
        # authoritative check inside the lock, but a re-delivery that
        # this process saw before short-circuits without acquiring the
        # lock at all.
        cached = self._dedupe.get(action.idempotency_key)
        if cached is not None:
            return await self._deduplicated_or_conflict(action=action, cached=cached)

        async with AsyncExitStack() as locks:
            await locks.enter_async_context(
                self._resource_lock.acquire(_idempotency_lock_key(action.idempotency_key))
            )
            cached = self._dedupe.get(action.idempotency_key)
            if cached is not None:
                return await self._deduplicated_or_conflict(action=action, cached=cached)
            await locks.enter_async_context(
                self._resource_lock.acquire(_resource_lock_key(action.target_resource_ref))
            )

            # Durable L2 guard - a mutation recorded under this key
            # (possibly before a restart) short-circuits the substrate
            # call. Only mutating outcomes are recorded.
            if self._idempotency is not None:
                stored = await self._idempotency.seen(action.idempotency_key)
                if stored is not None:
                    result = _da_result_from_payload(stored)
                    resolved = await self._deduplicated_or_conflict(
                        action=action,
                        cached=result,
                    )
                    if resolved is result:
                        self._remember(action.idempotency_key, result)
                    return resolved

            blast_reason = self._check_blast_radius(action)
            if blast_reason is not None:
                return await self._finish(
                    action=action,
                    outcome=DirectApiExecutionOutcome.ABSTAINED_BLAST_RADIUS,
                    reason=blast_reason,
                )

            request = _build_direct_api_request(action)
            try:
                receipt = await self._executor.execute(request)
            except DirectApiPromotionError as exc:
                return await self._finish(
                    action=action,
                    outcome=DirectApiExecutionOutcome.REJECTED_MODE,
                    reason=f"adapter refused promotion: {exc}",
                )
            except DirectApiPreconditionError as exc:
                return await self._finish(
                    action=action,
                    outcome=DirectApiExecutionOutcome.ABSTAINED_PRECONDITION,
                    reason=str(exc),
                )
            except DirectApiError as exc:
                return await self._finish(
                    action=action,
                    outcome=DirectApiExecutionOutcome.FAILED,
                    reason=f"adapter error [{exc.kind}]: {exc}",
                    rollback_succeeded=False,
                )
            except Exception as exc:  # noqa: BLE001 - executor boundary
                # Uncontrolled adapter failure: fail closed. Log via
                # module logger so an operator can investigate, then
                # audit the failure with rollback_succeeded=False so an
                # on-call sees the manual-rollback flag.
                _LOG.exception("direct-api adapter raised uncontrolled")
                return await self._finish(
                    action=action,
                    outcome=DirectApiExecutionOutcome.FAILED,
                    reason=f"uncontrolled adapter error: {exc!r}",
                    rollback_succeeded=False,
                )

            return await self._finish_from_receipt(action=action, receipt=receipt)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    async def _deduplicated_or_conflict(
        self,
        *,
        action: Action,
        cached: DirectApiExecutionResult,
    ) -> DirectApiExecutionResult:
        expected = _direct_api_fingerprint(action)
        recorded = cached.audit_context.get("idempotency_fingerprint")
        if recorded == expected:
            return cached
        return await self._finish(
            action=action,
            outcome=DirectApiExecutionOutcome.REJECTED_IDEMPOTENCY_CONFLICT,
            reason="idempotency key is already bound to a different action payload",
            remember=False,
        )

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
        self, *, action: Action, receipt: DirectApiReceipt
    ) -> DirectApiExecutionResult:
        """Map an adapter :class:`DirectApiReceipt` -> executor outcome + audit."""

        mapping: dict[DirectApiOutcome, DirectApiExecutionOutcome] = {
            DirectApiOutcome.SUCCEEDED: DirectApiExecutionOutcome.DISPATCHED,
            DirectApiOutcome.ALREADY_APPLIED: DirectApiExecutionOutcome.ALREADY_APPLIED,
            DirectApiOutcome.PRECONDITION_FAILED: (
                DirectApiExecutionOutcome.ABSTAINED_PRECONDITION
            ),
            DirectApiOutcome.STOPPED: DirectApiExecutionOutcome.STOPPED,
            DirectApiOutcome.FAILED: DirectApiExecutionOutcome.FAILED,
        }
        outcome = mapping[receipt.outcome]
        return await self._finish(
            action=action,
            outcome=outcome,
            reason=receipt.detail,
            receipt_ref=receipt.receipt_ref,
            rollback_succeeded=receipt.rollback_succeeded,
        )

    async def _finish(
        self,
        *,
        action: Action,
        outcome: DirectApiExecutionOutcome,
        reason: str | None,
        receipt_ref: str | None = None,
        rollback_succeeded: bool | None = None,
        remember: bool = True,
    ) -> DirectApiExecutionResult:
        result = DirectApiExecutionResult(
            action_id=str(action.action_id),
            outcome=outcome,
            mode=Mode.SHADOW,
            receipt_ref=receipt_ref,
            rollback_succeeded=rollback_succeeded,
            reason=reason,
            audit_context={
                "resource_ref": action.target_resource_ref,
                "action_type": action.action_type,
                "operation": action.operation.value,
                "blast_radius_scope": action.blast_radius.scope.value,
                "idempotency_fingerprint": _direct_api_fingerprint(action),
            },
        )
        # Cache non-degenerate outcomes so a retry does not re-hit the
        # adapter for the same key. Rejections (mode/invariant) are also
        # cached because they are stable properties of the Action itself.
        # Order matters: audit write MUST land before we populate the
        # cache, otherwise a raise from :meth:`_write_audit` would leave
        # a cached "already handled" hit that silently suppresses the
        # audit trail on the retry.
        await self._write_audit(action=action, result=result)
        if remember:
            self._remember(action.idempotency_key, result)
        # Durable dedup: record only mutating outcomes so a post-restart
        # retry does not re-hit the substrate. After the audit write for
        # the same reason _remember is.
        if remember and self._idempotency is not None and outcome in _DA_MUTATION_OUTCOMES:
            await self._idempotency.record(action.idempotency_key, _da_result_to_payload(result))
        return result

    def _remember(self, key: str, result: DirectApiExecutionResult) -> None:
        """FIFO-bounded insert. Mirrors :meth:`ShadowExecutor._remember`."""
        cap = max(1, self._config.max_dedupe_entries)
        if key in self._dedupe:
            del self._dedupe[key]
        elif len(self._dedupe) >= cap:
            self._dedupe.pop(next(iter(self._dedupe)))
        self._dedupe[key] = result

    async def _write_audit(self, *, action: Action, result: DirectApiExecutionResult) -> None:
        entry = {
            "event_id": str(action.event_id),
            "action_id": str(action.action_id),
            "idempotency_key": action.idempotency_key,
            "actor": "fdai.core.executor.direct_api",
            "action_kind": f"executor.direct_api.{result.outcome.value}",
            "mode": Mode.SHADOW.value,
            "execution_path": "direct_api",
            "citing_rule_ids": list(action.citing_rules),
            "outcome": result.outcome.value,
            "receipt_ref": result.receipt_ref,
            "rollback_succeeded": result.rollback_succeeded,
            "reason": result.reason,
            "resource_ref": action.target_resource_ref,
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


def _build_direct_api_request(action: Action) -> DirectApiRequest:
    """Assemble a :class:`DirectApiRequest` from one :class:`Action`.

    The adapter's ``arguments`` block is the ActionType's rendered
    param bundle (already scalar per the ActionBuilder contract); the
    executor never assembles substrate-specific payloads itself.
    """
    return DirectApiRequest(
        action_id=action.action_id,
        idempotency_key=action.idempotency_key,
        action_type_name=action.action_type,
        rule_ids=tuple(action.citing_rules),
        resource_ref=action.target_resource_ref,
        arguments=dict(action.params),
        labels=("shadow",),
        mode=Mode.SHADOW,
    )


__all__ = [
    "DirectApiExecutionOutcome",
    "DirectApiExecutionResult",
    "DirectApiShadowExecutor",
]
