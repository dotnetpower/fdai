"""Durable-record identity, keys, and codecs for workflow recovery.

The coordinator persists every recovery decision as an auditable record. This
module owns the exact key namespace and the strict mapping codecs those
records round-trip through, so a malformed or tampered record decodes to
``None`` instead of a silently weaker claim.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.workflow.recovery_admission import (
    WorkflowRecoveryAdmissionAssessment,
    WorkflowRecoveryAdmissionRejectionReason,
)
from fdai.core.workflow.recovery_attempt import (
    RecoveryAttemptIdentity,
    RecoveryAttemptRejectionReason,
    RecoveryDispatchResult,
    RecoveryPreDispatchClaim,
    recovery_attempt_idempotency_key,
)
from fdai.core.workflow.recovery_effect_claim import EffectCompletionClaim
from fdai.core.workflow.recovery_terminalization import (
    ReleaseReceiptLookup,
    TerminalTransitionRejection,
)
from fdai.core.workflow.workflow_runtime import WorkflowApprovalSnapshot
from fdai.shared.providers.state_store import StateStore

ACTOR = "fdai.core.workflow.recovery_coordinator"
ATTEMPT_PREFIX = "workflow:recovery-attempt:"
CLAIM_PREFIX = "workflow:recovery-claim:"
EFFECT_PREFIX = "workflow:recovery-effect:"
LOOKUP_PREFIX = "workflow:recovery-release-lookup:"
OUTBOX_PREFIX = "workflow:recovery-outbox:"

PROCESS_EVENT_DELIVERY = "process_event"
SAGA_AUDIT_DELIVERY = "saga_audit"

DIGEST_LENGTH = len("sha256:") + 64


def target_evidence_digest(target_ref: str) -> str:
    return f"sha256:{hashlib.sha256(target_ref.encode()).hexdigest()}"


async def read_recovery_attempt(
    store: StateStore,
    *,
    process_id: str,
    recovery_step_id: str,
) -> RecoveryAttemptIdentity | None:
    """Return the persisted recovery attempt one workflow step belongs to.

    A production writer that only sees workflow lineage uses this to rebind
    evidence to the exact attempt identity the coordinator already persisted.
    """

    record = await store.find_state(
        ATTEMPT_PREFIX,
        field="recovery_step_id",
        value=recovery_step_id,
    )
    if record is None or record.get("process_id") != process_id:
        return None
    return attempt_from_record(record)


def admission_reason(assessment: WorkflowRecoveryAdmissionAssessment) -> str:
    """Return the exact typed reason one ineligible admission MUST report."""

    if not assessment.rejection_reasons:
        return RecoveryAttemptRejectionReason.APPROVAL_MISSING
    ranked = {
        WorkflowRecoveryAdmissionRejectionReason.APPROVAL_REJECTED: 0,
        WorkflowRecoveryAdmissionRejectionReason.SELF_APPROVAL: 1,
        WorkflowRecoveryAdmissionRejectionReason.EXECUTOR_IDENTITY_NOT_DISTINCT: 2,
        WorkflowRecoveryAdmissionRejectionReason.APPROVAL_CANCELLED: 3,
        WorkflowRecoveryAdmissionRejectionReason.APPROVAL_TIMED_OUT: 4,
        WorkflowRecoveryAdmissionRejectionReason.APPROVAL_EXPIRED: 5,
        WorkflowRecoveryAdmissionRejectionReason.APPROVAL_EXPIRY_MISSING: 6,
        WorkflowRecoveryAdmissionRejectionReason.QUORUM_NOT_MET: 7,
    }
    ordered = sorted(
        assessment.rejection_reasons,
        key=lambda reason: (ranked.get(reason, len(ranked)), reason.value),
    )
    return ordered[0].value


def attempt_key(attempt: RecoveryAttemptIdentity) -> str:
    return f"{ATTEMPT_PREFIX}{attempt.identity_digest.removeprefix('sha256:')}"


def claim_key(attempt: RecoveryAttemptIdentity, hold_revision: int) -> str:
    digest = attempt.identity_digest.removeprefix("sha256:")
    return f"{CLAIM_PREFIX}{digest}:{hold_revision}"


def effect_key(attempt: RecoveryAttemptIdentity) -> str:
    return f"{EFFECT_PREFIX}{attempt.identity_digest.removeprefix('sha256:')}"


def lookup_key(
    attempt: RecoveryAttemptIdentity,
    effect_claim: EffectCompletionClaim,
    hold_revision: int,
) -> str:
    digest = content_digest(
        {
            "recovery_attempt_digest": attempt.identity_digest,
            "effect_claim_digest": effect_claim.claim_digest,
            "hold_revision": hold_revision,
        }
    )
    return f"{LOOKUP_PREFIX}{digest.removeprefix('sha256:')}"


def outbox_key(completion_digest: str, delivery_kind: str) -> str:
    return f"{OUTBOX_PREFIX}{completion_digest.removeprefix('sha256:')}:{delivery_kind}"


def recovery_action_id(attempt: RecoveryAttemptIdentity) -> str:
    return f"workflow-recovery:{attempt.identity_digest.removeprefix('sha256:')[:32]}"


def approval_digest(snapshot: WorkflowApprovalSnapshot) -> str:
    return content_digest(
        {
            "process_id": snapshot.process_id,
            "step_id": snapshot.step_id,
            "attempt": snapshot.attempt,
            "revision": snapshot.revision,
            "requester_principal": snapshot.requester_principal,
            "decisions": sorted(
                (decision.principal.strip().casefold(), decision.decision, decision.receipt_ref)
                for decision in snapshot.decisions
            ),
        }
    )


def approver_identity(snapshot: WorkflowApprovalSnapshot) -> str:
    approvers = sorted(
        decision.principal.strip().casefold()
        for decision in snapshot.decisions
        if decision.decision == "approved"
    )
    return approvers[0] if approvers else snapshot.requester_principal


def active_hold_revision(record: Mapping[str, Any] | None, *, process_id: str) -> int | None:
    if record is None or record.get("state") != "active":
        return None
    if record.get("process_id") != process_id:
        return None
    return int_or_none(record.get("revision"))


def int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def aware_or_none(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def attempt_from_record(record: Mapping[str, Any]) -> RecoveryAttemptIdentity | None:
    try:
        identity = RecoveryAttemptIdentity.create(
            process_id=str(record["process_id"]),
            failed_compensation_proposal_digest=str(record["failed_compensation_proposal_digest"]),
            hold_revision=int(str(record["hold_revision"])),
            recovery_action_type=str(record["recovery_action_type"]),
            recovery_payload_digest=str(record["recovery_payload_digest"]),
            target_digest=str(record["target_digest"]),
            source_revision=str(record["source_revision"]),
            attempt_number=int(str(record["attempt_number"])),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if identity.identity_digest != record.get("attempt_identity_digest"):
        return None
    return identity


def claim_from_record(
    record: Mapping[str, Any],
    *,
    attempt: RecoveryAttemptIdentity,
    hold_revision: int,
) -> RecoveryPreDispatchClaim | None:
    try:
        claim = RecoveryPreDispatchClaim.create(
            attempt_identity_digest=str(record["attempt_identity_digest"]),
            hold_revision=int(str(record["hold_revision"])),
            claim_revision=int(str(record["claim_revision"])),
            idempotency_key=str(record["idempotency_key"]),
            claimed_at=datetime.fromisoformat(str(record["claimed_at"])),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if (
        claim.attempt_identity_digest != attempt.identity_digest
        or claim.hold_revision != hold_revision
        or claim.claim_digest != record.get("claim_digest")
        or claim.idempotency_key != recovery_attempt_idempotency_key(attempt)
    ):
        return None
    return claim


def dispatch_from_record(
    record: Mapping[str, Any] | None,
    *,
    claim: RecoveryPreDispatchClaim,
) -> RecoveryDispatchResult | None:
    if record is None:
        return None
    outcome = record.get("dispatch_outcome")
    recorded_at = record.get("dispatch_recorded_at")
    if not isinstance(outcome, str) or not isinstance(recorded_at, str):
        return None
    receipt = record.get("provider_receipt_digest")
    try:
        result = RecoveryDispatchResult.create(
            attempt_identity_digest=claim.attempt_identity_digest,
            claim_digest=claim.claim_digest,
            outcome=outcome,
            provider_receipt_digest=receipt if isinstance(receipt, str) else None,
            recorded_at=datetime.fromisoformat(recorded_at),
        )
    except (TypeError, ValueError):
        return None
    if result.result_digest != record.get("dispatch_result_digest"):
        return None
    return result


def claim_records(record: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    raw = record.get("claims")
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        return ()
    return tuple(item for item in raw if isinstance(item, Mapping))


def observation_records(record: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    raw = record.get("observations")
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        return ()
    return tuple(item for item in raw if isinstance(item, Mapping))


def claim_to_record(claim: EffectCompletionClaim) -> dict[str, Any]:
    return {
        "attempt_identity_digest": claim.attempt_identity_digest,
        "action_digest": claim.action_digest,
        "safeguard_bundle_digest": claim.safeguard_bundle_digest,
        "provider_receipt_digest": claim.provider_receipt_digest,
        "target_digest": claim.target_digest,
        "expected_effect_digest": claim.expected_effect_digest,
        "approved_envelope_digest": claim.approved_envelope_digest,
        "source_revision": claim.source_revision,
        "evidence_window_start": claim.evidence_window_start.astimezone(UTC).isoformat(),
        "evidence_window_end": claim.evidence_window_end.astimezone(UTC).isoformat(),
        "effect_evidence_digest": claim.effect_evidence_digest,
        "validity_start": claim.validity_start.astimezone(UTC).isoformat(),
        "validity_end": claim.validity_end.astimezone(UTC).isoformat(),
        "watermark_set_digest": claim.watermark_set_digest,
        "hold_revision": claim.hold_revision,
        "admission_digest": claim.admission_digest,
        "success": claim.success,
        "generation": claim.generation,
        "superseded_by": claim.superseded_by,
        "claim_digest": claim.claim_digest,
        "execution_authority": False,
    }


def claim_from_mapping(record: Mapping[str, Any]) -> EffectCompletionClaim | None:
    try:
        return EffectCompletionClaim(
            attempt_identity_digest=str(record["attempt_identity_digest"]),
            action_digest=str(record["action_digest"]),
            safeguard_bundle_digest=str(record["safeguard_bundle_digest"]),
            provider_receipt_digest=str(record["provider_receipt_digest"]),
            target_digest=str(record["target_digest"]),
            expected_effect_digest=str(record["expected_effect_digest"]),
            approved_envelope_digest=str(record["approved_envelope_digest"]),
            source_revision=str(record["source_revision"]),
            evidence_window_start=datetime.fromisoformat(str(record["evidence_window_start"])),
            evidence_window_end=datetime.fromisoformat(str(record["evidence_window_end"])),
            effect_evidence_digest=str(record["effect_evidence_digest"]),
            validity_start=datetime.fromisoformat(str(record["validity_start"])),
            validity_end=datetime.fromisoformat(str(record["validity_end"])),
            watermark_set_digest=str(record["watermark_set_digest"]),
            hold_revision=int(str(record["hold_revision"])),
            admission_digest=str(record["admission_digest"]),
            success=bool(record["success"]),
            generation=int(str(record["generation"])),
            superseded_by=(
                str(record["superseded_by"]) if record.get("superseded_by") is not None else None
            ),
            claim_digest=str(record["claim_digest"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def lookup_from_record(record: Mapping[str, Any] | None) -> ReleaseReceiptLookup | None:
    if record is None:
        return None
    try:
        lookup = ReleaseReceiptLookup.create(
            recovery_attempt_digest=str(record["recovery_attempt_digest"]),
            effect_claim_digest=str(record["effect_claim_digest"]),
            hold_revision=int(str(record["hold_revision"])),
            release_receipt_digest=str(record["release_receipt_digest"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if lookup.lookup_digest != record.get("lookup_digest"):
        return None
    return lookup


def terminal_reason(reasons: tuple[TerminalTransitionRejection, ...]) -> str:
    return reasons[0].value if reasons else TerminalTransitionRejection.ALREADY_TERMINAL.value


__all__ = [
    "ACTOR",
    "ATTEMPT_PREFIX",
    "CLAIM_PREFIX",
    "DIGEST_LENGTH",
    "EFFECT_PREFIX",
    "LOOKUP_PREFIX",
    "OUTBOX_PREFIX",
    "PROCESS_EVENT_DELIVERY",
    "SAGA_AUDIT_DELIVERY",
    "active_hold_revision",
    "admission_reason",
    "approval_digest",
    "approver_identity",
    "attempt_from_record",
    "attempt_key",
    "aware_or_none",
    "claim_from_mapping",
    "claim_from_record",
    "claim_key",
    "claim_to_record",
    "claim_records",
    "dispatch_from_record",
    "effect_key",
    "int_or_none",
    "lookup_from_record",
    "lookup_key",
    "observation_records",
    "outbox_key",
    "read_recovery_attempt",
    "recovery_action_id",
    "target_evidence_digest",
    "terminal_reason",
]
