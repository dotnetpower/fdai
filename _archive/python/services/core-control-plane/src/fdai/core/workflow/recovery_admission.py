"""Fail-closed evidence admission for separately approved workflow recovery."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.workflow.approval_admission import workflow_approval_evidence_digest
from fdai.core.workflow.workflow_runtime import (
    WorkflowApprovalSnapshot,
    normalize_workflow_principal,
)
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    DecisionEvidenceAdmissionProvider,
    DecisionEvidenceAdmissionRejectionReason,
    assess_decision_evidence_admission,
)

WORKFLOW_RECOVERY_EVIDENCE_PURPOSE = "workflow-automation-hold-recovery"
_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


class WorkflowRecoveryAdmissionRejectionReason(StrEnum):
    """Why recovery evidence cannot proceed to atomic hold release."""

    APPROVAL_CANCELLED = "approval_cancelled"
    APPROVAL_EXPIRED = "approval_expired"
    APPROVAL_EXPIRY_MISSING = "approval_expiry_missing"
    APPROVAL_NOT_YET_REQUESTED = "approval_not_yet_requested"
    APPROVAL_DECISION_CONFLICT = "approval_decision_conflict"
    APPROVAL_REJECTED = "approval_rejected"
    APPROVAL_TIMED_OUT = "approval_timed_out"
    DECISION_EVIDENCE_ADMISSION_MISSING = "decision_evidence_admission_missing"
    DECISION_EVIDENCE_EVIDENCE_MISMATCH = "decision_evidence_evidence_mismatch"
    DECISION_EVIDENCE_NOT_CURRENT = "decision_evidence_not_current"
    DECISION_EVIDENCE_PROVIDER_FAILED = "decision_evidence_provider_failed"
    DECISION_EVIDENCE_PURPOSE_MISMATCH = "decision_evidence_purpose_mismatch"
    DECISION_EVIDENCE_SCOPE_MISMATCH = "decision_evidence_scope_mismatch"
    DECISION_EVIDENCE_SOURCE_REVISION_MISMATCH = "decision_evidence_source_revision_mismatch"
    EXECUTOR_IDENTITY_NOT_DISTINCT = "executor_identity_not_distinct"
    INVALID_RECOVERY_EVIDENCE = "invalid_recovery_evidence"
    NO_SELF_APPROVAL_DISABLED = "no_self_approval_disabled"
    QUORUM_NOT_MET = "quorum_not_met"
    SELF_APPROVAL = "self_approval"


_ADMISSION_REASON_MAP = {
    DecisionEvidenceAdmissionRejectionReason.EVIDENCE_MISMATCH: (
        WorkflowRecoveryAdmissionRejectionReason.DECISION_EVIDENCE_EVIDENCE_MISMATCH
    ),
    DecisionEvidenceAdmissionRejectionReason.NOT_CURRENT: (
        WorkflowRecoveryAdmissionRejectionReason.DECISION_EVIDENCE_NOT_CURRENT
    ),
    DecisionEvidenceAdmissionRejectionReason.PURPOSE_MISMATCH: (
        WorkflowRecoveryAdmissionRejectionReason.DECISION_EVIDENCE_PURPOSE_MISMATCH
    ),
    DecisionEvidenceAdmissionRejectionReason.SCOPE_MISMATCH: (
        WorkflowRecoveryAdmissionRejectionReason.DECISION_EVIDENCE_SCOPE_MISMATCH
    ),
    DecisionEvidenceAdmissionRejectionReason.SOURCE_REVISION_MISMATCH: (
        WorkflowRecoveryAdmissionRejectionReason.DECISION_EVIDENCE_SOURCE_REVISION_MISMATCH
    ),
}


@dataclass(frozen=True, slots=True)
class WorkflowRecoveryAdmissionAssessment:
    """Exact recovery eligibility with no hold-mutation or execution authority."""

    eligible: bool
    evidence_digest: str
    scope_digest: str
    source_revision: str
    rejection_reasons: tuple[WorkflowRecoveryAdmissionRejectionReason, ...]
    admission: DecisionEvidenceAdmission | None = None
    execution_authority: Literal[False] = False
    approval_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.eligible != (self.admission is not None):
            raise ValueError("workflow recovery admission eligibility mismatched admission")
        if self.eligible == bool(self.rejection_reasons):
            raise ValueError("workflow recovery admission eligibility mismatched reasons")
        if self.rejection_reasons != tuple(sorted(set(self.rejection_reasons), key=str)):
            raise ValueError("workflow recovery rejection reasons MUST be unique and ordered")
        if self.execution_authority or self.approval_authority:
            raise ValueError("workflow recovery admission MUST NOT grant authority")


def workflow_recovery_evidence_digest(
    snapshot: WorkflowApprovalSnapshot,
    *,
    quorum: int,
    no_self_approval: bool,
    hold_revision: int,
    target_digest: str,
    compensation_receipt_digests: tuple[str, ...],
    executor_identity: str,
    source_revision: str,
) -> str:
    """Bind exact approval, hold, compensation, executor, and source evidence."""

    _validate_recovery_inputs(
        snapshot=snapshot,
        quorum=quorum,
        hold_revision=hold_revision,
        target_digest=target_digest,
        compensation_receipt_digests=compensation_receipt_digests,
        executor_identity=executor_identity,
        source_revision=source_revision,
    )
    return content_digest(
        {
            "workflow_approval_evidence_digest": workflow_approval_evidence_digest(
                snapshot,
                quorum=quorum,
                no_self_approval=no_self_approval,
            ),
            "hold_revision": hold_revision,
            "target_digest": target_digest,
            "compensation_receipt_digests": compensation_receipt_digests,
            "executor_identity": normalize_workflow_principal(executor_identity),
            "source_revision": source_revision,
        }
    )


def workflow_recovery_scope_digest(
    snapshot: WorkflowApprovalSnapshot,
    *,
    hold_revision: int,
    target_digest: str,
) -> str:
    """Bind one recovery admission to an exact held Process and approval attempt."""

    if hold_revision < 1 or _DIGEST.fullmatch(target_digest) is None:
        raise ValueError("workflow recovery scope requires a hold revision and target digest")
    return content_digest(
        {
            "process_id": snapshot.process_id,
            "step_id": snapshot.step_id,
            "attempt": snapshot.attempt,
            "hold_revision": hold_revision,
            "target_digest": target_digest,
        }
    )


async def assess_workflow_recovery_admission(
    provider: DecisionEvidenceAdmissionProvider | None,
    *,
    snapshot: WorkflowApprovalSnapshot,
    quorum: int,
    no_self_approval: bool,
    hold_revision: int,
    target_digest: str,
    compensation_receipt_digests: tuple[str, ...],
    executor_identity: str,
    source_revision: str,
    evaluated_at: datetime,
) -> WorkflowRecoveryAdmissionAssessment:
    """Return an exact admitted recovery or typed fail-closed reasons."""

    evidence_digest = ""
    scope_digest = ""
    reasons = _approval_rejection_reasons(
        snapshot=snapshot,
        quorum=quorum,
        no_self_approval=no_self_approval,
        executor_identity=executor_identity,
        evaluated_at=evaluated_at,
    )
    try:
        evidence_digest = workflow_recovery_evidence_digest(
            snapshot,
            quorum=quorum,
            no_self_approval=no_self_approval,
            hold_revision=hold_revision,
            target_digest=target_digest,
            compensation_receipt_digests=compensation_receipt_digests,
            executor_identity=executor_identity,
            source_revision=source_revision,
        )
        scope_digest = workflow_recovery_scope_digest(
            snapshot,
            hold_revision=hold_revision,
            target_digest=target_digest,
        )
    except ValueError:
        reasons.add(WorkflowRecoveryAdmissionRejectionReason.INVALID_RECOVERY_EVIDENCE)
    if reasons:
        return _rejected(
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            source_revision=source_revision,
            reasons=reasons,
        )

    try:
        admission = (
            await provider.admit(
                evidence_digest=evidence_digest,
                scope_digest=scope_digest,
                purpose_id=WORKFLOW_RECOVERY_EVIDENCE_PURPOSE,
                source_revision=source_revision,
            )
            if provider is not None
            else None
        )
    except (LookupError, OSError, TimeoutError, RuntimeError, ValueError):
        return _rejected(
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            source_revision=source_revision,
            reasons={WorkflowRecoveryAdmissionRejectionReason.DECISION_EVIDENCE_PROVIDER_FAILED},
        )
    if admission is None:
        return _rejected(
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            source_revision=source_revision,
            reasons={WorkflowRecoveryAdmissionRejectionReason.DECISION_EVIDENCE_ADMISSION_MISSING},
        )
    admission_reasons = assess_decision_evidence_admission(
        admission,
        expected_evidence_digest=evidence_digest,
        expected_scope_digest=scope_digest,
        expected_purpose_id=WORKFLOW_RECOVERY_EVIDENCE_PURPOSE,
        expected_source_revision=source_revision,
        evaluated_at=evaluated_at,
    )
    if admission_reasons:
        return _rejected(
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            source_revision=source_revision,
            reasons={_ADMISSION_REASON_MAP[reason] for reason in admission_reasons},
        )
    return WorkflowRecoveryAdmissionAssessment(
        eligible=True,
        evidence_digest=evidence_digest,
        scope_digest=scope_digest,
        source_revision=source_revision,
        rejection_reasons=(),
        admission=admission,
    )


def _approval_rejection_reasons(
    *,
    snapshot: WorkflowApprovalSnapshot,
    quorum: int,
    no_self_approval: bool,
    executor_identity: str,
    evaluated_at: datetime,
) -> set[WorkflowRecoveryAdmissionRejectionReason]:
    reasons: set[WorkflowRecoveryAdmissionRejectionReason] = set()
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        reasons.add(WorkflowRecoveryAdmissionRejectionReason.INVALID_RECOVERY_EVIDENCE)
        return reasons
    normalized_at = evaluated_at.astimezone(UTC)
    if snapshot.requested_at.tzinfo is None or snapshot.requested_at.utcoffset() is None:
        reasons.add(WorkflowRecoveryAdmissionRejectionReason.INVALID_RECOVERY_EVIDENCE)
    elif snapshot.requested_at.astimezone(UTC) > normalized_at:
        reasons.add(WorkflowRecoveryAdmissionRejectionReason.APPROVAL_NOT_YET_REQUESTED)
    if snapshot.expires_at is None:
        reasons.add(WorkflowRecoveryAdmissionRejectionReason.APPROVAL_EXPIRY_MISSING)
    elif snapshot.expires_at.tzinfo is None or snapshot.expires_at.utcoffset() is None:
        reasons.add(WorkflowRecoveryAdmissionRejectionReason.INVALID_RECOVERY_EVIDENCE)
    elif normalized_at >= snapshot.expires_at.astimezone(UTC):
        reasons.add(WorkflowRecoveryAdmissionRejectionReason.APPROVAL_EXPIRED)
    if snapshot.cancelled:
        reasons.add(WorkflowRecoveryAdmissionRejectionReason.APPROVAL_CANCELLED)
    if snapshot.timed_out:
        reasons.add(WorkflowRecoveryAdmissionRejectionReason.APPROVAL_TIMED_OUT)
    if quorum < 1:
        reasons.add(WorkflowRecoveryAdmissionRejectionReason.INVALID_RECOVERY_EVIDENCE)
    if not no_self_approval:
        reasons.add(WorkflowRecoveryAdmissionRejectionReason.NO_SELF_APPROVAL_DISABLED)

    requester = normalize_workflow_principal(snapshot.requester_principal)
    executor = normalize_workflow_principal(executor_identity)
    if not requester or not executor:
        reasons.add(WorkflowRecoveryAdmissionRejectionReason.INVALID_RECOVERY_EVIDENCE)
    if executor == requester:
        reasons.add(WorkflowRecoveryAdmissionRejectionReason.EXECUTOR_IDENTITY_NOT_DISTINCT)
    approved: set[str] = set()
    decisions_by_principal: dict[str, str] = {}
    for decision in snapshot.decisions:
        principal = normalize_workflow_principal(decision.principal)
        if not principal:
            reasons.add(WorkflowRecoveryAdmissionRejectionReason.INVALID_RECOVERY_EVIDENCE)
            continue
        if principal in decisions_by_principal:
            reasons.add(WorkflowRecoveryAdmissionRejectionReason.APPROVAL_DECISION_CONFLICT)
        else:
            decisions_by_principal[principal] = decision.decision
        if principal == requester and decision.decision == "approved":
            reasons.add(WorkflowRecoveryAdmissionRejectionReason.SELF_APPROVAL)
        if principal == executor and decision.decision == "approved":
            reasons.add(WorkflowRecoveryAdmissionRejectionReason.EXECUTOR_IDENTITY_NOT_DISTINCT)
        if decision.decision == "approved" and principal not in {requester, executor}:
            approved.add(principal)
        elif decision.decision == "rejected":
            reasons.add(WorkflowRecoveryAdmissionRejectionReason.APPROVAL_REJECTED)
    if len(approved) < max(quorum, 1):
        reasons.add(WorkflowRecoveryAdmissionRejectionReason.QUORUM_NOT_MET)
    return reasons


def _validate_recovery_inputs(
    *,
    snapshot: WorkflowApprovalSnapshot,
    quorum: int,
    hold_revision: int,
    target_digest: str,
    compensation_receipt_digests: tuple[str, ...],
    executor_identity: str,
    source_revision: str,
) -> None:
    if (
        not snapshot.process_id
        or not snapshot.step_id
        or snapshot.attempt < 1
        or snapshot.revision < 1
        or quorum < 1
        or hold_revision < 1
        or _DIGEST.fullmatch(target_digest) is None
        or not normalize_workflow_principal(executor_identity)
        or not source_revision.strip()
        or len(source_revision) > 512
    ):
        raise ValueError("workflow recovery evidence identity is invalid")
    if (
        not compensation_receipt_digests
        or compensation_receipt_digests != tuple(sorted(compensation_receipt_digests))
        or len(compensation_receipt_digests) != len(set(compensation_receipt_digests))
        or any(_DIGEST.fullmatch(digest) is None for digest in compensation_receipt_digests)
    ):
        raise ValueError("workflow recovery compensation receipt digests are invalid")


def _rejected(
    *,
    evidence_digest: str,
    scope_digest: str,
    source_revision: str,
    reasons: set[WorkflowRecoveryAdmissionRejectionReason],
) -> WorkflowRecoveryAdmissionAssessment:
    return WorkflowRecoveryAdmissionAssessment(
        eligible=False,
        evidence_digest=evidence_digest,
        scope_digest=scope_digest,
        source_revision=source_revision,
        rejection_reasons=tuple(sorted(reasons, key=str)),
    )


__all__ = [
    "WORKFLOW_RECOVERY_EVIDENCE_PURPOSE",
    "WorkflowRecoveryAdmissionAssessment",
    "WorkflowRecoveryAdmissionRejectionReason",
    "assess_workflow_recovery_admission",
    "workflow_recovery_evidence_digest",
    "workflow_recovery_scope_digest",
]
