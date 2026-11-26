"""Durable CAS coordinator for control-plane recovery plan transitions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Final

from fdai.core.verticals.resilience.recovery_plan import (
    RecoveryPlan,
    RecoveryPlanError,
    RecoveryPlanStateMachine,
    RecoveryState,
    RecoveryTransition,
)
from fdai.core.verticals.resilience.recovery_record import (
    RecoveryPlanRecord,
    parse_recovery_record,
    recovery_state_key,
    recovery_utc,
    serialize_recovery_record,
)
from fdai.shared.providers.control_plane_recovery import (
    RecoveryApprovalEvidence,
    RecoveryApprovalVerifier,
)
from fdai.shared.providers.state_store import StateStore

_APPROVAL_STATES: Final[frozenset[RecoveryState]] = frozenset(
    {RecoveryState.APPROVED, RecoveryState.FAILBACK_READY}
)


class RecoveryCoordinatorError(RuntimeError):
    """Base failure for durable recovery plan coordination."""


class RecoveryWriteConflictError(RecoveryCoordinatorError):
    """The expected durable revision or state lost a concurrent race."""


class RecoveryApprovalError(RecoveryCoordinatorError):
    """A required approval is missing, invalid, or unavailable."""


class RecoveryRecordError(RecoveryCoordinatorError):
    """Persisted recovery state cannot be validated or replayed safely."""


class RecoveryPlanCoordinator:
    """Persist legal recovery transitions with approval and stale-write checks."""

    def __init__(
        self,
        *,
        state_store: StateStore,
        approval_verifier: RecoveryApprovalVerifier | None = None,
        state_machine: RecoveryPlanStateMachine | None = None,
    ) -> None:
        self._state_store = state_store
        self._approval_verifier = approval_verifier
        self._state_machine = state_machine or RecoveryPlanStateMachine()

    async def create(
        self,
        plan: RecoveryPlan,
        *,
        actor_ref: str,
        at: datetime,
        evidence_refs: Sequence[str],
    ) -> RecoveryPlanRecord:
        """Create one draft plan and its first audit row atomically."""
        if plan.state is not RecoveryState.DRAFT or plan.recovery_epoch != 0:
            raise RecoveryCoordinatorError("new recovery plan MUST start in draft at epoch zero")
        _require_time(at)
        transition = RecoveryTransition(
            plan_id=plan.plan_id,
            revision=plan.revision,
            from_state=RecoveryState.DRAFT,
            to_state=RecoveryState.READY,
            actor_ref=actor_ref,
            at=at,
            evidence_refs=tuple(evidence_refs),
            recovery_epoch=0,
        )
        create_key = _create_idempotency_key(
            plan=plan,
            actor_ref=actor_ref,
            at=at,
            evidence_refs=transition.evidence_refs,
        )
        record = RecoveryPlanRecord(
            plan=plan,
            storage_revision=0,
            last_transition_at=at,
            last_idempotency_key=create_key,
        )
        created = await self._state_store.write_state_with_audit_if_absent(
            recovery_state_key(plan.plan_id),
            serialize_recovery_record(record),
            _audit_entry(
                record=record,
                actor_ref=actor_ref,
                kind="recovery.plan.created",
                idempotency_key=create_key,
                evidence_refs=transition.evidence_refs,
                at=at,
            ),
        )
        if created:
            return record
        existing = await self.get(plan.plan_id)
        if existing is not None and existing == record:
            return existing
        raise RecoveryWriteConflictError(f"recovery plan {plan.plan_id!r} already exists")

    async def get(self, plan_id: str) -> RecoveryPlanRecord | None:
        """Read and validate the current durable recovery record."""
        raw = await self._state_store.read_state(recovery_state_key(plan_id))
        if raw is None:
            return None
        try:
            record = parse_recovery_record(raw)
        except (KeyError, TypeError, ValueError, RecoveryPlanError) as exc:
            raise RecoveryRecordError(f"recovery plan {plan_id!r} is corrupt") from exc
        if record.plan.plan_id != plan_id:
            raise RecoveryRecordError("recovery plan state key does not match payload plan_id")
        return record

    async def transition(
        self,
        *,
        plan_id: str,
        expected_storage_revision: int,
        expected_state: RecoveryState,
        target: RecoveryState,
        actor_ref: str,
        at: datetime,
        evidence_refs: Sequence[str],
        approval_ref: str | None = None,
        recovery_epoch: int | None = None,
    ) -> RecoveryPlanRecord:
        """Verify and atomically persist one legal transition."""
        current = await self.get(plan_id)
        if current is None:
            raise RecoveryWriteConflictError(f"recovery plan {plan_id!r} does not exist")
        intent_epoch = recovery_epoch if recovery_epoch is not None else current.plan.recovery_epoch
        intent: RecoveryTransition | None = None
        intent_error: RecoveryPlanError | None = None
        try:
            intent = RecoveryTransition(
                plan_id=current.plan.plan_id,
                revision=current.plan.revision,
                from_state=expected_state,
                to_state=target,
                actor_ref=actor_ref,
                at=at,
                evidence_refs=tuple(evidence_refs),
                recovery_epoch=intent_epoch,
                approval_ref=approval_ref,
            )
        except RecoveryPlanError as exc:
            intent_error = exc
        if intent is not None and current.last_idempotency_key == intent.idempotency_key:
            return current
        if current.storage_revision != expected_storage_revision:
            raise RecoveryWriteConflictError(
                f"storage revision conflict: expected={expected_storage_revision}, "
                f"current={current.storage_revision}"
            )
        if current.plan.state is not expected_state:
            raise RecoveryWriteConflictError(
                f"state conflict: expected={expected_state.value}, "
                f"current={current.plan.state.value}"
            )
        if intent_error is not None:
            raise RecoveryCoordinatorError(
                "recovery transition intent is invalid"
            ) from intent_error
        _require_time(at)
        if at < current.last_transition_at:
            raise RecoveryWriteConflictError("transition timestamp precedes the durable record")
        await self._verify_approval(
            plan=current.plan,
            target=target,
            actor_ref=actor_ref,
            approval_ref=approval_ref,
        )
        updated_plan, transition = self._state_machine.transition(
            current.plan,
            target=target,
            actor_ref=actor_ref,
            at=at,
            evidence_refs=evidence_refs,
            approval_ref=approval_ref,
            recovery_epoch=recovery_epoch,
        )
        updated = RecoveryPlanRecord(
            plan=updated_plan,
            storage_revision=current.storage_revision + 1,
            last_transition_at=at,
            last_idempotency_key=transition.idempotency_key,
        )
        applied = await self._state_store.compare_and_set_state_with_audit(
            recovery_state_key(plan_id),
            serialize_recovery_record(updated),
            expected_revision=current.storage_revision,
            audit_entry=_audit_entry(
                record=updated,
                actor_ref=actor_ref,
                kind="recovery.plan.transition",
                idempotency_key=transition.idempotency_key,
                evidence_refs=transition.evidence_refs,
                at=at,
                transition=transition,
            ),
        )
        if applied:
            return updated
        winner = await self.get(plan_id)
        if winner is not None and winner.last_idempotency_key == transition.idempotency_key:
            return winner
        raise RecoveryWriteConflictError("recovery transition lost a compare-and-set race")

    async def _verify_approval(
        self,
        *,
        plan: RecoveryPlan,
        target: RecoveryState,
        actor_ref: str,
        approval_ref: str | None,
    ) -> None:
        if target not in _APPROVAL_STATES:
            return
        if approval_ref is None or self._approval_verifier is None:
            raise RecoveryApprovalError("recovery approval verifier is not configured")
        try:
            verified = await self._approval_verifier.verify(
                RecoveryApprovalEvidence(
                    approval_ref=approval_ref,
                    actor_ref=actor_ref,
                    plan_id=plan.plan_id,
                    plan_revision=plan.revision,
                    target_state=target.value,
                )
            )
        except Exception as exc:  # noqa: BLE001 - provider boundary fails closed
            raise RecoveryApprovalError("recovery approval verification failed") from exc
        if not verified:
            raise RecoveryApprovalError("recovery approval was not verified")


def _create_idempotency_key(
    *,
    plan: RecoveryPlan,
    actor_ref: str,
    at: datetime,
    evidence_refs: Sequence[str],
) -> str:
    intent = json.dumps(
        {
            "actor_ref": actor_ref,
            "evidence_refs": list(evidence_refs),
            "plan": serialize_recovery_record(
                RecoveryPlanRecord(
                    plan=plan,
                    storage_revision=0,
                    last_transition_at=at,
                    last_idempotency_key="pending",
                )
            )["plan"],
            "recorded_at": recovery_utc(at),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return (
        f"{plan.plan_id}::{plan.revision}::created::{hashlib.sha256(intent.encode()).hexdigest()}"
    )


def _audit_entry(
    *,
    record: RecoveryPlanRecord,
    actor_ref: str,
    kind: str,
    idempotency_key: str,
    evidence_refs: Sequence[str],
    at: datetime,
    transition: RecoveryTransition | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "event_kind": "control_plane_recovery",
        "kind": kind,
        "plan_id": record.plan.plan_id,
        "plan_revision": record.plan.revision,
        "storage_revision": record.storage_revision,
        "state": record.plan.state.value,
        "mode": record.plan.mode.value,
        "recovery_epoch": record.plan.recovery_epoch,
        "actor": actor_ref,
        "correlation_id": record.plan.plan_id,
        "idempotency_key": idempotency_key,
        "evidence_refs": list(evidence_refs),
        "recorded_at": recovery_utc(at),
    }
    if transition is not None:
        entry["from_state"] = transition.from_state.value
        entry["to_state"] = transition.to_state.value
        entry["approval_ref"] = transition.approval_ref
    return entry


def _require_time(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RecoveryCoordinatorError("timestamp MUST be timezone-aware")


__all__ = [
    "RecoveryApprovalError",
    "RecoveryCoordinatorError",
    "RecoveryPlanCoordinator",
    "RecoveryPlanRecord",
    "RecoveryRecordError",
    "RecoveryWriteConflictError",
]
