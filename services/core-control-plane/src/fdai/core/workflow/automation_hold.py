"""Durable target automation holds for incomplete workflow recovery."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol, runtime_checkable

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.workflow.recovery_admission import (
    WORKFLOW_RECOVERY_EVIDENCE_PURPOSE,
    WorkflowRecoveryAdmissionAssessment,
    workflow_recovery_evidence_digest,
    workflow_recovery_scope_digest,
)
from fdai.core.workflow.recovery_attempt import is_recovery_attempt_step_id
from fdai.core.workflow.workflow_runtime import (
    WorkflowApprovalSnapshot,
    workflow_approval_state_key,
)
from fdai.shared.providers.decision_evidence_verifier import assess_decision_evidence_admission
from fdai.shared.providers.resource_lock import ResourceLock, resource_lock_key
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger(__name__)

_KEY_PREFIX = "workflow:automation-hold:"
_RELEASE_INTENT_PREFIX = "workflow:automation-hold-release-intent:"
_RELEASE_AUTHORIZATION_PREFIX = "workflow:automation-hold-dispatch-authorization:"
HOLD_SCOPED_AUTHORIZATION = "hold_scoped"
RELEASED_AUTHORIZATION = "released"


@runtime_checkable
class ApprovalGuardedStateStore(Protocol):
    """Atomically mutate state only while one approval row remains current."""

    async def compare_and_set_state_with_approval_guard(
        self,
        key: str,
        value: Mapping[str, object],
        *,
        expected_revision: int,
        approval_key: str,
        expected_approval_revision: int,
        expected_approval_process_id: str,
        expected_approval_step_id: str,
        expected_approval_attempt: int,
        expected_approval_requester: str,
        expected_approval_quorum: int,
        expected_no_self_approval: bool,
        expected_approval_decisions: tuple[tuple[str, str, str], ...],
        evaluated_at: datetime,
        admission_verified_at: datetime,
        admission_valid_until: datetime,
        audit_entry: Mapping[str, object],
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class AutomationHoldReleaseReceipt:
    """Content-addressed hold release result with no execution authority."""

    action_id: str
    target_digest: str
    process_id: str
    released_hold_revision: int
    fencing_generation: int
    recovery_admission_digest: str
    recovery_evidence_digest: str
    compensation_receipt_digests: tuple[str, ...]
    source_revision: str
    released_at: datetime
    receipt_digest: str
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.execution_authority:
            raise ValueError("automation hold release receipt MUST NOT grant execution authority")
        expected = content_digest(
            {
                **asdict(self),
                "released_at": self.released_at.astimezone(UTC).isoformat(),
                "receipt_digest": None,
            }
        )
        if self.receipt_digest != expected:
            raise ValueError("automation hold release receipt digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        action_id: str,
        target_digest: str,
        process_id: str,
        released_hold_revision: int,
        fencing_generation: int,
        recovery_admission_digest: str,
        recovery_evidence_digest: str,
        compensation_receipt_digests: tuple[str, ...],
        source_revision: str,
        released_at: datetime,
    ) -> AutomationHoldReleaseReceipt:
        """Create one canonical receipt from an atomically committed release."""

        normalized_released_at = released_at.astimezone(UTC)
        digest = content_digest(
            {
                "action_id": action_id,
                "target_digest": target_digest,
                "process_id": process_id,
                "released_hold_revision": released_hold_revision,
                "fencing_generation": fencing_generation,
                "recovery_admission_digest": recovery_admission_digest,
                "recovery_evidence_digest": recovery_evidence_digest,
                "compensation_receipt_digests": compensation_receipt_digests,
                "source_revision": source_revision,
                "released_at": normalized_released_at.isoformat(),
                "execution_authority": False,
                "receipt_digest": None,
            }
        )
        return cls(
            action_id=action_id,
            target_digest=target_digest,
            process_id=process_id,
            released_hold_revision=released_hold_revision,
            fencing_generation=fencing_generation,
            recovery_admission_digest=recovery_admission_digest,
            recovery_evidence_digest=recovery_evidence_digest,
            compensation_receipt_digests=compensation_receipt_digests,
            source_revision=source_revision,
            released_at=normalized_released_at,
            receipt_digest=digest,
            execution_authority=False,
        )

    def to_mapping(self) -> dict[str, object]:
        """Return the canonical state and audit representation."""

        return {
            **asdict(self),
            "released_at": self.released_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class StateStoreAutomationHoldLedger:
    """Issue immutable recovery holds and read their fail-closed state."""

    store: StateStore
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(tz=UTC))
    resource_lock: ResourceLock | None = None

    async def issue(
        self,
        *,
        target_ref: str,
        process_id: str,
        reason: str,
    ) -> None:
        if self.resource_lock is not None:
            async with self.resource_lock.acquire(resource_lock_key(target_ref)):
                await self._issue_unlocked(
                    target_ref=target_ref,
                    process_id=process_id,
                    reason=reason,
                )
            return
        await self._issue_unlocked(
            target_ref=target_ref,
            process_id=process_id,
            reason=reason,
        )

    async def _issue_unlocked(
        self,
        *,
        target_ref: str,
        process_id: str,
        reason: str,
    ) -> None:
        target_digest = _target_digest(target_ref)
        key = _state_key(target_ref)
        for _ in range(3):
            existing = await self.store.read_state(key)
            if existing is not None and existing.get("state") != "released":
                return
            revision = int(existing.get("revision", 0)) + 1 if existing is not None else 1
            record = {
                "target_digest": target_digest,
                "process_id": process_id,
                "reason": reason,
                "state": "active",
                "created_at": self.clock().astimezone(UTC).isoformat(),
                "revision": revision,
            }
            audit_entry = {
                "actor": "fdai.core.workflow.automation_hold",
                "action_kind": "workflow.automation_hold.issued",
                **record,
            }
            if existing is None:
                if await self.store.write_state_with_audit_if_absent(
                    key,
                    record,
                    audit_entry,
                ):
                    return
            elif await self.store.compare_and_set_state_with_audit(
                key,
                record,
                expected_revision=revision - 1,
                audit_entry=audit_entry,
            ):
                return
        raise RuntimeError("automation hold issue conflicted repeatedly")

    async def recovery_eligible(
        self,
        *,
        target_ref: str,
        process_id: str,
        step_id: str,
    ) -> bool:
        """Whether one exact step holds proven authority to act under this hold.

        The hold denies every ordinary forward dispatch on the target. The one
        exception is the recovery step the coordinator separately authorized
        under the hold revision that is still active, so this reads that proof
        instead of inferring intent from a step name. A readable prefix is not
        authority: a step that does not have the canonical recovery-attempt
        shape, belongs to another Process, names another target, or cites a
        superseded hold revision is refused. An authorization that exists but
        cannot be read raises, so the caller fails closed instead of reading
        unusable evidence as "no exception".
        """

        if not is_recovery_attempt_step_id(step_id):
            return False
        record = await self.store.read_state(_state_key(target_ref))
        revision = _int_or_none(record.get("revision")) if isinstance(record, Mapping) else None
        if revision is None or not _matches_active_hold(
            record, target_ref=target_ref, process_id=process_id, hold_revision=revision
        ):
            return False
        authorization = await self.read_dispatch_authorization(
            target_ref=target_ref, process_id=process_id, step_id=step_id
        )
        return bool(
            authorization is not None
            and authorization.get("authorization_kind") == HOLD_SCOPED_AUTHORIZATION
            and authorization.get("authorized_hold_revision") == revision
        )

    async def release_admitted(
        self,
        *,
        target_ref: str,
        process_id: str,
        action_id: str,
        hold_revision: int,
        approval_snapshot: WorkflowApprovalSnapshot,
        quorum: int,
        no_self_approval: bool,
        compensation_receipt_digests: tuple[str, ...],
        executor_identity: str,
        source_revision: str,
        assessment: WorkflowRecoveryAdmissionAssessment,
        workflow_lineage: tuple[str, str] | None = None,
    ) -> AutomationHoldReleaseReceipt | None:
        """Atomically consume exact admitted recovery and release one hold revision.

        ``workflow_lineage`` is the exact ``(process_id, step_id)`` the released
        target authorizes for forward dispatch. The executor fence reads its
        expected lineage from that binding, so a hold reissued and re-released
        afterwards denies dispatch instead of matching it.
        """

        if not action_id.strip() or not assessment.eligible or assessment.admission is None:
            return None
        target_digest = _target_evidence_digest(target_ref)
        if approval_snapshot.process_id != process_id:
            return None
        try:
            evidence_digest = workflow_recovery_evidence_digest(
                approval_snapshot,
                quorum=quorum,
                no_self_approval=no_self_approval,
                hold_revision=hold_revision,
                target_digest=target_digest,
                compensation_receipt_digests=compensation_receipt_digests,
                executor_identity=executor_identity,
                source_revision=source_revision,
            )
            scope_digest = workflow_recovery_scope_digest(
                approval_snapshot,
                hold_revision=hold_revision,
                target_digest=target_digest,
            )
        except ValueError:
            return None
        if (
            assessment.evidence_digest != evidence_digest
            or assessment.scope_digest != scope_digest
            or assessment.source_revision != source_revision
            or assessment.admission.evidence_digest != evidence_digest
            or assessment.admission.scope_digest != scope_digest
            or assessment.admission.source_revision != source_revision
        ):
            return None

        key = _state_key(target_ref)
        record = await self.store.read_state(key)
        existing_receipt = _matching_release_receipt(
            record,
            action_id=action_id,
            process_id=process_id,
            hold_revision=hold_revision,
            recovery_admission_digest=assessment.admission.receipt_digest,
        )
        if existing_receipt is not None:
            await self._record_release_authorization(
                target_ref=target_ref,
                receipt=existing_receipt,
                recovery_admission_digest=assessment.admission.receipt_digest,
                workflow_lineage=workflow_lineage,
            )
            return existing_receipt
        evaluated_at = self.clock()
        if not _approval_is_current(approval_snapshot, evaluated_at=evaluated_at):
            return None
        if assess_decision_evidence_admission(
            assessment.admission,
            expected_evidence_digest=evidence_digest,
            expected_scope_digest=scope_digest,
            expected_purpose_id=WORKFLOW_RECOVERY_EVIDENCE_PURPOSE,
            expected_source_revision=source_revision,
            evaluated_at=evaluated_at,
        ):
            return None
        if not _matches_active_hold(
            record,
            target_ref=target_ref,
            process_id=process_id,
            hold_revision=hold_revision,
        ):
            return None
        if not isinstance(record, Mapping):
            return None
        if not isinstance(self.store, ApprovalGuardedStateStore):
            return None

        intent = {
            "action_id": action_id,
            "target_digest": target_digest,
            "process_id": process_id,
            "hold_revision": hold_revision,
            "recovery_admission_digest": assessment.admission.receipt_digest,
            "recovery_evidence_digest": evidence_digest,
            "compensation_receipt_digests": list(compensation_receipt_digests),
            "source_revision": source_revision,
            "requested_at": evaluated_at.astimezone(UTC).isoformat(),
            "revision": 1,
        }
        intent_key = _release_intent_key(assessment.admission.receipt_digest)
        created = await self.store.write_state_with_audit_if_absent(
            intent_key,
            intent,
            {
                "actor": "fdai.core.workflow.automation_hold",
                "action_kind": "workflow.automation_hold.release_intent",
                **intent,
            },
        )
        if not created:
            existing_intent = await self.store.read_state(intent_key)
            if not _same_release_intent(existing_intent, intent):
                return None
            if not isinstance(existing_intent, Mapping):
                return None
            intent = dict(existing_intent)

        released_at = _intent_requested_at(intent)
        if released_at is None:
            return None
        receipt = AutomationHoldReleaseReceipt.create(
            action_id=action_id,
            target_digest=target_digest,
            process_id=process_id,
            released_hold_revision=hold_revision,
            fencing_generation=hold_revision + 1,
            recovery_admission_digest=assessment.admission.receipt_digest,
            recovery_evidence_digest=evidence_digest,
            compensation_receipt_digests=compensation_receipt_digests,
            source_revision=source_revision,
            released_at=released_at,
        )
        released = {
            **dict(record),
            "state": "released",
            "revision": hold_revision + 1,
            "fencing_generation": hold_revision + 1,
            "consumed_recovery_admission_digest": assessment.admission.receipt_digest,
            "release_receipt": receipt.to_mapping(),
            "released_at": released_at.isoformat(),
        }
        terminal_evaluated_at = self.clock()
        if not _approval_is_current(
            approval_snapshot,
            evaluated_at=terminal_evaluated_at,
        ):
            return None
        if assess_decision_evidence_admission(
            assessment.admission,
            expected_evidence_digest=evidence_digest,
            expected_scope_digest=scope_digest,
            expected_purpose_id=WORKFLOW_RECOVERY_EVIDENCE_PURPOSE,
            expected_source_revision=source_revision,
            evaluated_at=terminal_evaluated_at,
        ):
            return None
        committed = await self.store.compare_and_set_state_with_approval_guard(
            key,
            released,
            expected_revision=hold_revision,
            approval_key=workflow_approval_state_key(
                approval_snapshot.process_id,
                approval_snapshot.step_id,
                approval_snapshot.attempt,
            ),
            expected_approval_revision=approval_snapshot.revision,
            expected_approval_process_id=approval_snapshot.process_id,
            expected_approval_step_id=approval_snapshot.step_id,
            expected_approval_attempt=approval_snapshot.attempt,
            expected_approval_requester=approval_snapshot.requester_principal,
            expected_approval_quorum=quorum,
            expected_no_self_approval=no_self_approval,
            expected_approval_decisions=tuple(
                sorted(
                    (
                        decision.principal.strip().casefold(),
                        decision.decision,
                        decision.receipt_ref,
                    )
                    for decision in approval_snapshot.decisions
                )
            ),
            evaluated_at=terminal_evaluated_at,
            admission_verified_at=assessment.admission.verified_at,
            admission_valid_until=assessment.admission.valid_until,
            audit_entry={
                "actor": "fdai.core.workflow.automation_hold",
                "action_kind": "workflow.automation_hold.released_admitted",
                "target_digest": target_digest,
                "process_id": process_id,
                "released_hold_revision": hold_revision,
                "fencing_generation": hold_revision + 1,
                "recovery_admission_digest": assessment.admission.receipt_digest,
                "release_receipt_digest": receipt.receipt_digest,
                "released_at": released_at.isoformat(),
            },
        )
        if committed:
            await self._record_release_authorization(
                target_ref=target_ref,
                receipt=receipt,
                recovery_admission_digest=assessment.admission.receipt_digest,
                workflow_lineage=workflow_lineage,
            )
            return receipt
        existing = _matching_release_receipt(
            await self.store.read_state(key),
            action_id=action_id,
            process_id=process_id,
            hold_revision=hold_revision,
            recovery_admission_digest=assessment.admission.receipt_digest,
        )
        if existing is not None:
            await self._record_release_authorization(
                target_ref=target_ref,
                receipt=existing,
                recovery_admission_digest=assessment.admission.receipt_digest,
                workflow_lineage=workflow_lineage,
            )
        return existing

    async def authorize_hold_scoped_dispatch(
        self,
        *,
        target_ref: str,
        process_id: str,
        step_id: str,
        hold_revision: int,
    ) -> bool:
        """Authorize one approved step to dispatch under this exact hold revision.

        A held target denies every ordinary forward dispatch. The approved
        recovery step for the Process that owns the hold is the one exception,
        and it is bound to the exact hold revision it was approved under, so a
        hold reissued or released after this authorization denies dispatch
        instead of racing it (#640).
        """

        if not step_id.strip() or not process_id.strip() or hold_revision < 1:
            return False
        record = await self.store.read_state(_state_key(target_ref))
        if not _matches_active_hold(
            record,
            target_ref=target_ref,
            process_id=process_id,
            hold_revision=hold_revision,
        ):
            return False
        authorization = {
            "target_digest": _target_evidence_digest(target_ref),
            "authorization_kind": HOLD_SCOPED_AUTHORIZATION,
            "process_id": process_id,
            "step_id": step_id,
            "authorized_hold_revision": hold_revision,
            "execution_authority": False,
            "revision": 1,
        }
        key = _dispatch_authorization_key(target_ref, process_id, step_id)
        created = await self.store.write_state_with_audit_if_absent(
            key,
            authorization,
            {
                "actor": "fdai.core.workflow.automation_hold",
                "action_kind": "workflow.automation_hold.hold_scoped_dispatch_authorized",
                **authorization,
            },
        )
        if created:
            return True
        stored = await self.store.read_state(key)
        return bool(
            stored is not None
            and stored.get("authorization_kind") == HOLD_SCOPED_AUTHORIZATION
            and stored.get("process_id") == process_id
            and stored.get("step_id") == step_id
            and stored.get("authorized_hold_revision") == hold_revision
        )

    async def _record_release_authorization(
        self,
        *,
        target_ref: str,
        receipt: AutomationHoldReleaseReceipt,
        recovery_admission_digest: str,
        workflow_lineage: tuple[str, str] | None,
    ) -> None:
        """Bind the exact release lineage one action was authorized under.

        A later forward dispatch MUST take its expected lineage from this
        immutable authorization, never from whatever hold record happens to be
        current at dispatch time (#640). The release itself already committed,
        so a write failure here is logged and never discards the receipt.
        """

        if workflow_lineage is None:
            return
        process_id, step_id = workflow_lineage
        if not process_id.strip() or not step_id.strip():
            return
        key = _dispatch_authorization_key(target_ref, process_id, step_id)
        record = {
            "target_digest": receipt.target_digest,
            "authorization_kind": RELEASED_AUTHORIZATION,
            "action_id": receipt.action_id,
            "process_id": process_id,
            "step_id": step_id,
            "release_receipt_digest": receipt.receipt_digest,
            "released_hold_revision": receipt.released_hold_revision,
            "fencing_generation": receipt.fencing_generation,
            "recovery_admission_digest": recovery_admission_digest,
            "source_revision": receipt.source_revision,
            "released_at": receipt.released_at.astimezone(UTC).isoformat(),
            "execution_authority": False,
            "revision": 1,
        }
        try:
            created = await self.store.write_state_with_audit_if_absent(
                key,
                record,
                {
                    "actor": "fdai.core.workflow.automation_hold",
                    "action_kind": "workflow.automation_hold.release_authorization_bound",
                    **record,
                },
            )
            if created:
                return
            await self._replace_hold_scoped_authorization(key=key, record=record)
        except Exception:  # noqa: BLE001 - the release already committed
            _LOGGER.exception(
                "automation_hold_release_authorization_write_failed",
                extra={"process_id": process_id},
            )

    async def _replace_hold_scoped_authorization(
        self,
        *,
        key: str,
        record: Mapping[str, object],
    ) -> None:
        """Promote the hold-scoped authorization to the release it produced."""

        for _ in range(3):
            stored = await self.store.read_state(key)
            if stored is None:
                return
            if stored.get("authorization_kind") == RELEASED_AUTHORIZATION:
                return
            revision = stored.get("revision")
            if not isinstance(revision, int) or isinstance(revision, bool):
                return
            if await self.store.compare_and_set_state_with_audit(
                key,
                {**dict(record), "revision": revision + 1},
                expected_revision=revision,
                audit_entry={
                    "actor": "fdai.core.workflow.automation_hold",
                    "action_kind": "workflow.automation_hold.release_authorization_bound",
                    **dict(record),
                },
            ):
                return

    async def read_dispatch_authorization(
        self,
        *,
        target_ref: str,
        process_id: str,
        step_id: str,
    ) -> Mapping[str, object] | None:
        """Return the dispatch authorization bound to one exact workflow step.

        A stored authorization that does not belong to this target and step is
        unusable evidence, so it raises instead of reading as "no authorization".
        """

        if not process_id.strip() or not step_id.strip():
            return None
        record = await self.store.read_state(
            _dispatch_authorization_key(target_ref, process_id, step_id)
        )
        if record is None:
            return None
        if (
            record.get("target_digest") != _target_evidence_digest(target_ref)
            or record.get("process_id") != process_id
            or record.get("step_id") != step_id
            or record.get("authorization_kind")
            not in {HOLD_SCOPED_AUTHORIZATION, RELEASED_AUTHORIZATION}
        ):
            raise ValueError("automation hold dispatch authorization is unreadable")
        return dict(record)

    async def is_held(self, *, target_ref: str) -> bool:
        record = await self.store.read_state(_state_key(target_ref))
        if record is None:
            return False
        return not (
            record.get("target_digest") == _target_digest(target_ref)
            and record.get("state") == "released"
        )

    async def read_hold_record(self, *, target_ref: str) -> Mapping[str, object] | None:
        """Return the raw hold record for fencing and recovery reads.

        The record is evidence only. Callers MUST classify it before acting;
        it never grants execution, release, or approval authority.
        """

        record = await self.store.read_state(_state_key(target_ref))
        if record is None or record.get("target_digest") != _target_digest(target_ref):
            return None
        return dict(record)


def _target_digest(target_ref: str) -> str:
    return hashlib.sha256(target_ref.encode()).hexdigest()


def _target_evidence_digest(target_ref: str) -> str:
    return f"sha256:{_target_digest(target_ref)}"


def _state_key(target_ref: str) -> str:
    return f"{_KEY_PREFIX}{_target_digest(target_ref)}"


def _release_intent_key(admission_digest: str) -> str:
    return f"{_RELEASE_INTENT_PREFIX}{admission_digest.removeprefix('sha256:')}"


def _dispatch_authorization_key(target_ref: str, process_id: str, step_id: str) -> str:
    identity = f"{_target_digest(target_ref)}\0{process_id}\0{step_id}"
    digest = hashlib.sha256(identity.encode()).hexdigest()
    return f"{_RELEASE_AUTHORIZATION_PREFIX}{digest}"


def _matches_active_hold(
    record: object,
    *,
    target_ref: str,
    process_id: str,
    hold_revision: int,
) -> bool:
    return bool(
        isinstance(record, Mapping)
        and record.get("target_digest") == _target_digest(target_ref)
        and record.get("state") == "active"
        and record.get("process_id") == process_id
        and record.get("revision") == hold_revision
    )


def _int_or_none(value: object) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return value


def _same_release_intent(record: object, expected: Mapping[str, object]) -> bool:
    return bool(
        isinstance(record, Mapping)
        and all(
            record.get(key) == value for key, value in expected.items() if key != "requested_at"
        )
    )


def _intent_requested_at(record: Mapping[str, object]) -> datetime | None:
    raw = record.get("requested_at")
    if not isinstance(raw, str):
        return None
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(UTC)


def _approval_is_current(
    snapshot: WorkflowApprovalSnapshot,
    *,
    evaluated_at: datetime,
) -> bool:
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        return False
    if snapshot.cancelled or snapshot.timed_out or snapshot.expires_at is None:
        return False
    if snapshot.expires_at.tzinfo is None or snapshot.expires_at.utcoffset() is None:
        return False
    if snapshot.requested_at.tzinfo is None or snapshot.requested_at.utcoffset() is None:
        return False
    normalized_at = evaluated_at.astimezone(UTC)
    return (
        snapshot.requested_at.astimezone(UTC) <= normalized_at < snapshot.expires_at.astimezone(UTC)
    )


def _matching_release_receipt(
    record: object,
    *,
    action_id: str,
    process_id: str,
    hold_revision: int,
    recovery_admission_digest: str,
) -> AutomationHoldReleaseReceipt | None:
    if not isinstance(record, Mapping) or record.get("state") != "released":
        return None
    raw = record.get("release_receipt")
    if not isinstance(raw, Mapping):
        return None
    if (
        raw.get("action_id") != action_id
        or raw.get("process_id") != process_id
        or raw.get("released_hold_revision") != hold_revision
        or raw.get("recovery_admission_digest") != recovery_admission_digest
        or raw.get("execution_authority") is not False
    ):
        return None
    try:
        raw_receipts = raw["compensation_receipt_digests"]
        if not isinstance(raw_receipts, list | tuple) or not all(
            isinstance(item, str) for item in raw_receipts
        ):
            return None
        return AutomationHoldReleaseReceipt(
            action_id=str(raw["action_id"]),
            target_digest=str(raw["target_digest"]),
            process_id=str(raw["process_id"]),
            released_hold_revision=int(raw["released_hold_revision"]),
            fencing_generation=int(raw["fencing_generation"]),
            recovery_admission_digest=str(raw["recovery_admission_digest"]),
            recovery_evidence_digest=str(raw["recovery_evidence_digest"]),
            compensation_receipt_digests=tuple(raw_receipts),
            source_revision=str(raw["source_revision"]),
            released_at=datetime.fromisoformat(str(raw["released_at"])),
            receipt_digest=str(raw["receipt_digest"]),
            execution_authority=False,
        )
    except (KeyError, TypeError, ValueError):
        return None


__all__ = ["AutomationHoldReleaseReceipt", "StateStoreAutomationHoldLedger"]
