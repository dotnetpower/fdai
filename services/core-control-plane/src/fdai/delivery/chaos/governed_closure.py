"""Audited, human-approved closure of chaos runs that still hold their targets.

A run that escalated, failed after an attempted injection, or was orphaned by a
stopped process keeps its targets claimed because FDAI could not verify that the
substrate recovered. Only a separate closure decision releases those claims: the
injected verifier's ``verify_closure`` must confirm a distinct Var approver for
that exact run and its targets, and the approval that authorized the run's
injection is refused. Closure is addressed by target, so an orphaned run whose
request can no longer be rebuilt can still be closed. Closing a run that has not
reached ``injecting`` also denies it through a compare-and-swap, so a concurrent
process can never inject it. Each closure is a create-only record with a Saga
audit entry, and every refused closure is audited too.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from fdai.core.chaos.run_state import ChaosRunState
from fdai.core.chaos.run_store import ChaosRunConflictError, ChaosRunStore
from fdai.delivery.chaos.governed_bindings import (
    CHAOS_CLOSURE_INTENT,
    ChaosApprovalEvidence,
    GovernedChaosBindings,
)
from fdai.delivery.chaos.governed_claims import (
    ChaosTargetClaims,
    approval_digest,
    closure_record_key,
    held_target_locks,
    target_digest,
)
from fdai.delivery.chaos.governed_records import CHAOS_ACTION_TYPE, PRE_INJECTION_STATES
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.tool import ToolCallRequest

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ChaosClosureResult:
    """The closure decision for one target; ``closed`` means its claim is released."""

    target_digest: str
    run_id: str | None
    closed: bool
    reason: str


def closure_request(
    *,
    run_id: str,
    targets: tuple[str, ...],
    approval_ref: str,
    reason: str,
) -> ToolCallRequest:
    """Build the typed closure intent the injected Var verifier must approve."""

    return ToolCallRequest(
        action_id=uuid5(NAMESPACE_URL, f"urn:fdai:chaos-closure:{run_id}:{_digest(approval_ref)}"),
        idempotency_key=f"chaos-closure:{run_id}",
        action_type_name=CHAOS_ACTION_TYPE,
        rule_ids=(),
        tool_ref=run_id,
        arguments={"closure_of_run_id": run_id, "targets": sorted(targets)},
        labels=("enforce", "closure"),
        mode=Mode.ENFORCE,
        metadata={"approval_ref": approval_ref, "intent": "closure", "closure_reason": reason},
    )


def closure_refusal(
    evidence: object,
    approval_ref: str,
    *,
    run_id: str,
    targets: tuple[str, ...],
) -> str | None:
    """Return why ``evidence`` cannot approve closing ``run_id``, or ``None`` when it can."""

    if not isinstance(evidence, ChaosApprovalEvidence):
        return "approval_unverified"
    if evidence.intent != CHAOS_CLOSURE_INTENT:
        return "closure_intent_missing"
    if evidence.run_id != run_id or set(evidence.target_digests) != {
        target_digest(item) for item in targets
    }:
        return "closure_scope_mismatch"
    if evidence.approval_principal != "Var":
        return "var_approval_required"
    if evidence.approval_ref != approval_ref or not evidence.initiator_id.strip():
        return "approval_unverified"
    approvers = {item.casefold() for item in evidence.approver_ids if item.strip()}
    if not approvers:
        return "approval_quorum_not_met"
    if evidence.initiator_id.casefold() in approvers:
        return "self_approval_forbidden"
    return None


class GovernedChaosClosure:
    """Release escalated or orphaned targets only through an approved closure record."""

    def __init__(
        self,
        *,
        bindings: GovernedChaosBindings,
        clock: Callable[[], datetime] | None = None,
        lock_timeout_seconds: float = 30.0,
    ) -> None:
        if not isinstance(bindings, GovernedChaosBindings):
            raise TypeError("governed chaos closure requires GovernedChaosBindings")
        if lock_timeout_seconds <= 0:
            raise ValueError("closure lock timeout MUST be positive")
        self._bindings = bindings
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._lock_timeout = lock_timeout_seconds
        self._run_store = ChaosRunStore(state_store=bindings.state_store)
        self._claims = ChaosTargetClaims(
            state_store=bindings.state_store,
            run_store=self._run_store,
        )

    async def close_targets(
        self,
        *,
        targets: tuple[str, ...],
        approval_ref: str,
        reason: str,
    ) -> tuple[ChaosClosureResult, ...]:
        """Close the run holding each target under the distributed target locks.

        Raises:
            ValueError: the targets, approval claim, or reason are missing.
            ToolPreconditionError: the target locks are unavailable.
        """

        normalized = tuple(sorted({item.strip() for item in targets}))
        if not normalized or "" in normalized or not approval_ref.strip() or not reason.strip():
            raise ValueError("closure requires targets, an approval claim, and a reason")
        async with held_target_locks(
            self._bindings.target_lock,
            normalized,
            timeout=self._lock_timeout,
        ):
            return tuple(
                [
                    await self._close_one(target, normalized, approval_ref, reason.strip())
                    for target in normalized
                ]
            )

    async def _close_one(
        self,
        target: str,
        targets: tuple[str, ...],
        approval_ref: str,
        reason: str,
    ) -> ChaosClosureResult:
        digest = target_digest(target)
        holder = await self._claims.holder(target)
        if holder is None:
            return ChaosClosureResult(digest, None, closed=False, reason="no_claim")
        if await self._claims.closed(holder):
            return ChaosClosureResult(digest, holder, closed=True, reason="already_closed")
        if await self._claims.released(holder):
            return ChaosClosureResult(digest, holder, closed=False, reason="already_released")
        binding = await self._claims.binding(holder)
        if binding is None:
            refusal: str | None = "run_binding_missing"
            evidence: object = None
        elif binding.get("approval_digest") == approval_digest(approval_ref):
            refusal, evidence = "closure_reuses_enforce_approval", None
        else:
            evidence = await self._verified(holder, targets, approval_ref, reason)
            refusal = closure_refusal(evidence, approval_ref, run_id=holder, targets=targets)
        if refusal is None and not await self._deny_before_injection(holder):
            refusal = "holder_changed"
        if refusal is not None or not isinstance(evidence, ChaosApprovalEvidence):
            refusal = refusal or "approval_unverified"
            await self._audit_refusal(holder, targets, approval_ref, refusal)
            return ChaosClosureResult(digest, holder, closed=False, reason=refusal)
        created = await self._bindings.state_store.write_state_with_audit_if_absent(
            closure_record_key(holder),
            self._closure_record(holder, targets, evidence, reason),
            self._audit(holder, targets, evidence, reason),
        )
        return ChaosClosureResult(
            digest,
            holder,
            closed=True,
            reason="closed" if created else "already_closed",
        )

    async def _verified(
        self,
        run_id: str,
        targets: tuple[str, ...],
        approval_ref: str,
        reason: str,
    ) -> object:
        request = closure_request(
            run_id=run_id,
            targets=targets,
            approval_ref=approval_ref,
            reason=reason,
        )
        try:
            return await self._bindings.approval_verifier.verify_closure(request, run_id=run_id)
        except Exception as exc:  # noqa: BLE001 - an unverifiable closure never releases a target
            _LOGGER.warning(
                "governed_chaos_closure_unverified",
                extra={"run_id": run_id, "error_type": type(exc).__name__},
            )
            return None

    async def _deny_before_injection(self, run_id: str) -> bool:
        """Deny a holder that has not reached ``injecting``; the CAS fences a racing injector."""

        snapshot = await self._run_store.get(run_id)
        if snapshot is None or snapshot.state not in PRE_INJECTION_STATES:
            return True
        try:
            await self._run_store.transition(
                snapshot,
                target=ChaosRunState.DENIED,
                idempotency_key=f"{run_id}:{ChaosRunState.DENIED.value}",
                at=self._now(),
            )
        except (ChaosRunConflictError, ValueError):
            return False
        return True

    def _closure_record(
        self,
        run_id: str,
        targets: tuple[str, ...],
        evidence: ChaosApprovalEvidence,
        reason: str,
    ) -> dict[str, object]:
        return {
            "run_id": run_id,
            "approval_ref": evidence.approval_ref,
            "approval_principal": evidence.approval_principal,
            "approver_ids": sorted(evidence.approver_ids),
            "initiator_id": evidence.initiator_id,
            "reason": reason,
            "target_digests": sorted(target_digest(item) for item in targets),
            "closed_at": self._now().isoformat(),
        }

    def _audit(
        self,
        run_id: str,
        targets: tuple[str, ...],
        evidence: ChaosApprovalEvidence,
        reason: str,
    ) -> dict[str, object]:
        return {
            "event_id": f"{run_id}:closure",
            "idempotency_key": f"{run_id}:closure",
            "actor": "Saga",
            "producer_principal": "Saga",
            "action_kind": "chaos.run.closure",
            "mode": Mode.ENFORCE.value,
            "run_id": run_id,
            "approval_principal": evidence.approval_principal,
            "approver_ids": sorted(evidence.approver_ids),
            "initiator_id": evidence.initiator_id,
            "reason": reason,
            "target_digests": sorted(target_digest(item) for item in targets),
            "recorded_at": self._now().isoformat(),
        }

    async def _audit_refusal(
        self,
        run_id: str,
        targets: tuple[str, ...],
        approval_ref: str,
        refusal: str,
    ) -> None:
        event_id = f"{run_id}:closure-refused:{_digest(approval_ref)[:16]}:{refusal}"
        entry = {
            "event_id": event_id,
            "idempotency_key": event_id,
            "actor": "Saga",
            "producer_principal": "Saga",
            "action_kind": "chaos.run.closure.refused",
            "mode": Mode.ENFORCE.value,
            "run_id": run_id,
            "reason": refusal,
            "target_digests": sorted(target_digest(item) for item in targets),
            "recorded_at": self._now().isoformat(),
        }
        try:
            await self._bindings.state_store.append_audit_entry(entry)
        except Exception:  # noqa: BLE001 - the refused closure still releases nothing
            _LOGGER.error("governed_chaos_closure_refusal_unaudited", extra={"run_id": run_id})

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise RuntimeError("governed chaos closure clock MUST be timezone-aware")
        return value.astimezone(UTC)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "ChaosClosureResult",
    "GovernedChaosClosure",
    "closure_refusal",
    "closure_request",
]
