"""Exact admission tests for separately approved workflow recovery."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.workflow.recovery_admission import (
    WORKFLOW_RECOVERY_EVIDENCE_PURPOSE,
    WorkflowRecoveryAdmissionAssessment,
    WorkflowRecoveryAdmissionRejectionReason,
    assess_workflow_recovery_admission,
    workflow_recovery_evidence_digest,
)
from fdai.core.workflow.workflow_runtime import (
    WorkflowApprovalDecision,
    WorkflowApprovalSnapshot,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission

_NOW = datetime(2026, 9, 10, 2, 0, tzinfo=UTC)
_TARGET_DIGEST = "sha256:" + "a" * 64
_RECEIPTS = ("sha256:" + "b" * 64, "sha256:" + "c" * 64)
_SOURCE_REVISION = "commit:" + "d" * 40


class _Unset:
    pass


_UNSET = _Unset()


def _snapshot(
    *,
    process_id: str = "process-1",
    step_id: str = "approve_recovery",
    requester_principal: str = "requester@example.com",
    revision: int = 3,
    requested_at: datetime | None = None,
    expires_at: datetime | None | _Unset = _UNSET,
    attempt: int = 2,
    decisions: tuple[WorkflowApprovalDecision, ...] | None = None,
    timed_out: bool = False,
    cancelled: bool = False,
) -> WorkflowApprovalSnapshot:
    resolved_expires_at = (
        _NOW + timedelta(minutes=3) if isinstance(expires_at, _Unset) else expires_at
    )
    return WorkflowApprovalSnapshot(
        process_id=process_id,
        step_id=step_id,
        requester_principal=requester_principal,
        revision=revision,
        requested_at=requested_at or _NOW - timedelta(minutes=2),
        expires_at=resolved_expires_at,
        attempt=attempt,
        decisions=(
            (
                WorkflowApprovalDecision(
                    principal="approver@example.com",
                    decision="approved",
                    receipt_ref="approval:1",
                ),
            )
            if decisions is None
            else decisions
        ),
        timed_out=timed_out,
        cancelled=cancelled,
    )


class _Provider:
    def __init__(
        self,
        *,
        evidence_digest: str | None = None,
        scope_digest: str | None = None,
        purpose_id: str | None = None,
        source_revision: str | None = None,
        valid_until: datetime | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.evidence_digest = evidence_digest
        self.scope_digest = scope_digest
        self.purpose_id = purpose_id
        self.source_revision = source_revision
        self.valid_until = valid_until
        self.failure = failure
        self.calls: list[dict[str, str]] = []

    async def admit(
        self,
        *,
        evidence_digest: str,
        scope_digest: str,
        purpose_id: str,
        source_revision: str,
    ) -> DecisionEvidenceAdmission:
        if self.failure is not None:
            raise self.failure
        self.calls.append(
            {
                "evidence_digest": evidence_digest,
                "scope_digest": scope_digest,
                "purpose_id": purpose_id,
                "source_revision": source_revision,
            }
        )
        return DecisionEvidenceAdmission(
            receipt_digest="sha256:" + "e" * 64,
            verification_bundle_digest="sha256:" + "f" * 64,
            evidence_digest=self.evidence_digest or evidence_digest,
            scope_digest=self.scope_digest or scope_digest,
            purpose_id=self.purpose_id or purpose_id,
            source_revision=self.source_revision or source_revision,
            verified_at=_NOW - timedelta(minutes=1),
            valid_until=self.valid_until or _NOW + timedelta(minutes=1),
        )


async def _assess(
    *,
    snapshot: WorkflowApprovalSnapshot | None = None,
    provider: _Provider | None = None,
    quorum: int = 1,
    no_self_approval: bool = True,
    executor_identity: str = "executor@example.com",
    evaluated_at: datetime = _NOW,
    compensation_receipt_digests: tuple[str, ...] = _RECEIPTS,
) -> WorkflowRecoveryAdmissionAssessment:
    return await assess_workflow_recovery_admission(
        provider or _Provider(),
        snapshot=snapshot or _snapshot(),
        quorum=quorum,
        no_self_approval=no_self_approval,
        hold_revision=4,
        target_digest=_TARGET_DIGEST,
        compensation_receipt_digests=compensation_receipt_digests,
        executor_identity=executor_identity,
        source_revision=_SOURCE_REVISION,
        evaluated_at=evaluated_at,
    )


async def test_matching_approval_and_decision_evidence_admits_recovery_only() -> None:
    provider = _Provider()

    result = await _assess(provider=provider)

    assert result.eligible is True
    assert result.rejection_reasons == ()
    assert result.admission is not None
    assert result.execution_authority is result.approval_authority is False
    assert provider.calls[0]["purpose_id"] == WORKFLOW_RECOVERY_EVIDENCE_PURPOSE


@pytest.mark.parametrize(
    ("snapshot", "quorum", "no_self_approval", "executor_identity", "reason"),
    [
        (
            _snapshot(cancelled=True),
            1,
            True,
            "executor@example.com",
            WorkflowRecoveryAdmissionRejectionReason.APPROVAL_CANCELLED,
        ),
        (
            _snapshot(timed_out=True),
            1,
            True,
            "executor@example.com",
            WorkflowRecoveryAdmissionRejectionReason.APPROVAL_TIMED_OUT,
        ),
        (
            _snapshot(expires_at=None),
            1,
            True,
            "executor@example.com",
            WorkflowRecoveryAdmissionRejectionReason.APPROVAL_EXPIRY_MISSING,
        ),
        (
            _snapshot(expires_at=_NOW - timedelta(seconds=1)),
            1,
            True,
            "executor@example.com",
            WorkflowRecoveryAdmissionRejectionReason.APPROVAL_EXPIRED,
        ),
        (
            _snapshot(expires_at=_NOW),
            1,
            True,
            "executor@example.com",
            WorkflowRecoveryAdmissionRejectionReason.APPROVAL_EXPIRED,
        ),
        (
            _snapshot(requested_at=_NOW + timedelta(seconds=1)),
            1,
            True,
            "executor@example.com",
            WorkflowRecoveryAdmissionRejectionReason.APPROVAL_NOT_YET_REQUESTED,
        ),
        (
            _snapshot(),
            2,
            True,
            "executor@example.com",
            WorkflowRecoveryAdmissionRejectionReason.QUORUM_NOT_MET,
        ),
        (
            _snapshot(),
            1,
            False,
            "executor@example.com",
            WorkflowRecoveryAdmissionRejectionReason.NO_SELF_APPROVAL_DISABLED,
        ),
        (
            _snapshot(),
            1,
            True,
            "requester@example.com",
            WorkflowRecoveryAdmissionRejectionReason.EXECUTOR_IDENTITY_NOT_DISTINCT,
        ),
        (
            _snapshot(
                decisions=(
                    WorkflowApprovalDecision(
                        principal="requester@example.com",
                        decision="approved",
                        receipt_ref="approval:self",
                    ),
                )
            ),
            1,
            True,
            "executor@example.com",
            WorkflowRecoveryAdmissionRejectionReason.SELF_APPROVAL,
        ),
        (
            _snapshot(
                decisions=(
                    WorkflowApprovalDecision(
                        principal="approver@example.com",
                        decision="approved",
                        receipt_ref="approval:approved",
                    ),
                    WorkflowApprovalDecision(
                        principal="operator@example.com",
                        decision="rejected",
                        receipt_ref="approval:rejected",
                    ),
                )
            ),
            1,
            True,
            "executor@example.com",
            WorkflowRecoveryAdmissionRejectionReason.APPROVAL_REJECTED,
        ),
        (
            _snapshot(
                decisions=(
                    WorkflowApprovalDecision(
                        principal="approver@example.com",
                        decision="approved",
                        receipt_ref="approval:approved",
                    ),
                    WorkflowApprovalDecision(
                        principal="APPROVER@example.com",
                        decision="rejected",
                        receipt_ref="approval:rejected",
                    ),
                )
            ),
            1,
            True,
            "executor@example.com",
            WorkflowRecoveryAdmissionRejectionReason.APPROVAL_DECISION_CONFLICT,
        ),
    ],
)
async def test_invalid_approval_or_identity_fails_before_provider(
    snapshot: WorkflowApprovalSnapshot,
    quorum: int,
    no_self_approval: bool,
    executor_identity: str,
    reason: WorkflowRecoveryAdmissionRejectionReason,
) -> None:
    provider = _Provider()

    result = await _assess(
        snapshot=snapshot,
        provider=provider,
        quorum=quorum,
        no_self_approval=no_self_approval,
        executor_identity=executor_identity,
    )

    assert result.eligible is False
    assert reason in result.rejection_reasons
    assert result.admission is None
    assert provider.calls == []


@pytest.mark.parametrize(
    ("provider", "reason"),
    [
        (
            _Provider(evidence_digest="sha256:" + "0" * 64),
            WorkflowRecoveryAdmissionRejectionReason.DECISION_EVIDENCE_EVIDENCE_MISMATCH,
        ),
        (
            _Provider(scope_digest="sha256:" + "0" * 64),
            WorkflowRecoveryAdmissionRejectionReason.DECISION_EVIDENCE_SCOPE_MISMATCH,
        ),
        (
            _Provider(purpose_id="different-purpose"),
            WorkflowRecoveryAdmissionRejectionReason.DECISION_EVIDENCE_PURPOSE_MISMATCH,
        ),
        (
            _Provider(source_revision="commit:" + "0" * 40),
            WorkflowRecoveryAdmissionRejectionReason.DECISION_EVIDENCE_SOURCE_REVISION_MISMATCH,
        ),
        (
            _Provider(valid_until=_NOW - timedelta(seconds=1)),
            WorkflowRecoveryAdmissionRejectionReason.DECISION_EVIDENCE_NOT_CURRENT,
        ),
    ],
)
async def test_mismatched_or_expired_admission_fails_closed(
    provider: _Provider,
    reason: WorkflowRecoveryAdmissionRejectionReason,
) -> None:
    result = await _assess(provider=provider)

    assert result.eligible is False
    assert result.rejection_reasons == (reason,)
    assert result.admission is None


async def test_missing_or_malformed_recovery_evidence_fails_closed() -> None:
    missing = await assess_workflow_recovery_admission(
        None,
        snapshot=_snapshot(),
        quorum=1,
        no_self_approval=True,
        hold_revision=4,
        target_digest=_TARGET_DIGEST,
        compensation_receipt_digests=_RECEIPTS,
        executor_identity="executor@example.com",
        source_revision=_SOURCE_REVISION,
        evaluated_at=_NOW,
    )
    malformed = await _assess(
        compensation_receipt_digests=tuple(reversed(_RECEIPTS)),
    )

    assert missing.rejection_reasons == (
        WorkflowRecoveryAdmissionRejectionReason.DECISION_EVIDENCE_ADMISSION_MISSING,
    )
    assert malformed.rejection_reasons == (
        WorkflowRecoveryAdmissionRejectionReason.INVALID_RECOVERY_EVIDENCE,
    )


async def test_provider_failure_becomes_a_typed_rejection() -> None:
    result = await _assess(provider=_Provider(failure=TimeoutError("provider timeout")))

    assert result.rejection_reasons == (
        WorkflowRecoveryAdmissionRejectionReason.DECISION_EVIDENCE_PROVIDER_FAILED,
    )
    assert result.admission is None


def test_recovery_digest_changes_for_every_replay_sensitive_input() -> None:
    base = workflow_recovery_evidence_digest(
        _snapshot(),
        quorum=1,
        no_self_approval=True,
        hold_revision=4,
        target_digest=_TARGET_DIGEST,
        compensation_receipt_digests=_RECEIPTS,
        executor_identity="executor@example.com",
        source_revision=_SOURCE_REVISION,
    )
    variants = (
        workflow_recovery_evidence_digest(
            replace(_snapshot(), process_id="process-other"),
            quorum=1,
            no_self_approval=True,
            hold_revision=4,
            target_digest=_TARGET_DIGEST,
            compensation_receipt_digests=_RECEIPTS,
            executor_identity="executor@example.com",
            source_revision=_SOURCE_REVISION,
        ),
        workflow_recovery_evidence_digest(
            replace(_snapshot(), step_id="approve_other"),
            quorum=1,
            no_self_approval=True,
            hold_revision=4,
            target_digest=_TARGET_DIGEST,
            compensation_receipt_digests=_RECEIPTS,
            executor_identity="executor@example.com",
            source_revision=_SOURCE_REVISION,
        ),
        workflow_recovery_evidence_digest(
            replace(_snapshot(), attempt=3),
            quorum=1,
            no_self_approval=True,
            hold_revision=4,
            target_digest=_TARGET_DIGEST,
            compensation_receipt_digests=_RECEIPTS,
            executor_identity="executor@example.com",
            source_revision=_SOURCE_REVISION,
        ),
        workflow_recovery_evidence_digest(
            replace(_snapshot(), revision=4),
            quorum=1,
            no_self_approval=True,
            hold_revision=4,
            target_digest=_TARGET_DIGEST,
            compensation_receipt_digests=_RECEIPTS,
            executor_identity="executor@example.com",
            source_revision=_SOURCE_REVISION,
        ),
        workflow_recovery_evidence_digest(
            _snapshot(),
            quorum=1,
            no_self_approval=True,
            hold_revision=5,
            target_digest=_TARGET_DIGEST,
            compensation_receipt_digests=_RECEIPTS,
            executor_identity="executor@example.com",
            source_revision=_SOURCE_REVISION,
        ),
        workflow_recovery_evidence_digest(
            _snapshot(),
            quorum=1,
            no_self_approval=True,
            hold_revision=4,
            target_digest="sha256:" + "1" * 64,
            compensation_receipt_digests=_RECEIPTS,
            executor_identity="executor@example.com",
            source_revision=_SOURCE_REVISION,
        ),
        workflow_recovery_evidence_digest(
            _snapshot(),
            quorum=1,
            no_self_approval=True,
            hold_revision=4,
            target_digest=_TARGET_DIGEST,
            compensation_receipt_digests=("sha256:" + "2" * 64,),
            executor_identity="executor@example.com",
            source_revision=_SOURCE_REVISION,
        ),
        workflow_recovery_evidence_digest(
            _snapshot(),
            quorum=1,
            no_self_approval=True,
            hold_revision=4,
            target_digest=_TARGET_DIGEST,
            compensation_receipt_digests=_RECEIPTS,
            executor_identity="other-executor@example.com",
            source_revision=_SOURCE_REVISION,
        ),
        workflow_recovery_evidence_digest(
            _snapshot(),
            quorum=1,
            no_self_approval=True,
            hold_revision=4,
            target_digest=_TARGET_DIGEST,
            compensation_receipt_digests=_RECEIPTS,
            executor_identity="executor@example.com",
            source_revision="commit:" + "3" * 40,
        ),
    )
    assert all(variant != base for variant in variants)
