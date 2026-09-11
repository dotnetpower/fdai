"""Focused deterministic tests for recovery attempt dispatch (#652)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.workflow.recovery_attempt import (
    RecoveryApprovalEvidence,
    RecoveryAttemptIdentity,
    RecoveryDispatchOutcome,
    RecoveryDispatchResult,
    RecoveryPreDispatchClaim,
    RecoverySafeguardEvidence,
    recovery_attempt_idempotency_key,
)

_NOW = datetime(2026, 9, 11, 0, 0, tzinfo=UTC)
_COMP_DIGEST = "sha256:" + "a" * 64
_PAYLOAD_DIGEST = "sha256:" + "b" * 64
_TARGET_DIGEST = "sha256:" + "c" * 64
_RECEIPT_DIGEST = "sha256:" + "d" * 64
_APPROVAL_DIGEST = "sha256:" + "e" * 64
_SAFEGUARD_DIGEST = "sha256:" + "f" * 64


def _make_identity(*, attempt_number: int = 1) -> RecoveryAttemptIdentity:
    return RecoveryAttemptIdentity.create(
        process_id="process-1",
        failed_compensation_proposal_digest=_COMP_DIGEST,
        hold_revision=1,
        recovery_action_type="restart_pod",
        recovery_payload_digest=_PAYLOAD_DIGEST,
        target_digest=_TARGET_DIGEST,
        source_revision="commit:" + "0" * 40,
        attempt_number=attempt_number,
    )


class TestRecoveryAttemptIdentity:
    def test_create_valid(self) -> None:
        identity = _make_identity()
        assert identity.process_id == "process-1"
        assert identity.attempt_number == 1
        assert identity.execution_authority is False
        assert identity.identity_digest.startswith("sha256:")

    def test_deterministic_digest(self) -> None:
        a = _make_identity()
        b = _make_identity()
        assert a.identity_digest == b.identity_digest

    def test_different_attempt_different_digest(self) -> None:
        a = _make_identity(attempt_number=1)
        b = _make_identity(attempt_number=2)
        assert a.identity_digest != b.identity_digest

    def test_reject_execution_authority(self) -> None:
        identity = _make_identity()
        with pytest.raises(ValueError, match="execution authority"):
            RecoveryAttemptIdentity(
                process_id=identity.process_id,
                failed_compensation_proposal_digest=identity.failed_compensation_proposal_digest,
                hold_revision=identity.hold_revision,
                recovery_action_type=identity.recovery_action_type,
                recovery_payload_digest=identity.recovery_payload_digest,
                target_digest=identity.target_digest,
                source_revision=identity.source_revision,
                attempt_number=identity.attempt_number,
                identity_digest=identity.identity_digest,
                execution_authority=True,  # type: ignore[arg-type]
            )

    def test_reject_empty_process_id(self) -> None:
        with pytest.raises(ValueError, match="process_id"):
            RecoveryAttemptIdentity.create(
                process_id="",
                failed_compensation_proposal_digest=_COMP_DIGEST,
                hold_revision=1,
                recovery_action_type="restart_pod",
                recovery_payload_digest=_PAYLOAD_DIGEST,
                target_digest=_TARGET_DIGEST,
                source_revision="commit:" + "0" * 40,
                attempt_number=1,
            )

    def test_reject_zero_attempt_number(self) -> None:
        with pytest.raises(ValueError, match="attempt_number"):
            RecoveryAttemptIdentity.create(
                process_id="process-1",
                failed_compensation_proposal_digest=_COMP_DIGEST,
                hold_revision=1,
                recovery_action_type="restart_pod",
                recovery_payload_digest=_PAYLOAD_DIGEST,
                target_digest=_TARGET_DIGEST,
                source_revision="commit:" + "0" * 40,
                attempt_number=0,
            )

    def test_reject_invalid_compensation_digest(self) -> None:
        with pytest.raises(ValueError, match="compensation proposal"):
            RecoveryAttemptIdentity.create(
                process_id="process-1",
                failed_compensation_proposal_digest="bad",
                hold_revision=1,
                recovery_action_type="restart_pod",
                recovery_payload_digest=_PAYLOAD_DIGEST,
                target_digest=_TARGET_DIGEST,
                source_revision="commit:" + "0" * 40,
                attempt_number=1,
            )

    def test_reject_tampered_digest(self) -> None:
        identity = _make_identity()
        with pytest.raises(ValueError, match="mismatched"):
            RecoveryAttemptIdentity(
                process_id=identity.process_id,
                failed_compensation_proposal_digest=identity.failed_compensation_proposal_digest,
                hold_revision=identity.hold_revision,
                recovery_action_type=identity.recovery_action_type,
                recovery_payload_digest=identity.recovery_payload_digest,
                target_digest=identity.target_digest,
                source_revision=identity.source_revision,
                attempt_number=identity.attempt_number,
                identity_digest="sha256:" + "9" * 64,
            )

    def test_failed_proposal_immutability(self) -> None:
        """Failed compensation proposal digest is embedded in the identity."""
        a = RecoveryAttemptIdentity.create(
            process_id="process-1",
            failed_compensation_proposal_digest=_COMP_DIGEST,
            hold_revision=1,
            recovery_action_type="restart_pod",
            recovery_payload_digest=_PAYLOAD_DIGEST,
            target_digest=_TARGET_DIGEST,
            source_revision="commit:" + "0" * 40,
            attempt_number=1,
        )
        b = RecoveryAttemptIdentity.create(
            process_id="process-1",
            failed_compensation_proposal_digest="sha256:" + "9" * 64,
            hold_revision=1,
            recovery_action_type="restart_pod",
            recovery_payload_digest=_PAYLOAD_DIGEST,
            target_digest=_TARGET_DIGEST,
            source_revision="commit:" + "0" * 40,
            attempt_number=1,
        )
        assert a.identity_digest != b.identity_digest


class TestPreDispatchClaim:
    def test_create_valid(self) -> None:
        identity = _make_identity()
        claim = RecoveryPreDispatchClaim.create(
            attempt_identity_digest=identity.identity_digest,
            hold_revision=1,
            claim_revision=1,
            idempotency_key="key-1",
            claimed_at=_NOW,
        )
        assert claim.execution_authority is False
        assert claim.claim_digest.startswith("sha256:")

    def test_deterministic(self) -> None:
        identity = _make_identity()
        a = RecoveryPreDispatchClaim.create(
            attempt_identity_digest=identity.identity_digest,
            hold_revision=1,
            claim_revision=1,
            idempotency_key="key-1",
            claimed_at=_NOW,
        )
        b = RecoveryPreDispatchClaim.create(
            attempt_identity_digest=identity.identity_digest,
            hold_revision=1,
            claim_revision=1,
            idempotency_key="key-1",
            claimed_at=_NOW,
        )
        assert a.claim_digest == b.claim_digest

    def test_reject_naive_datetime(self) -> None:
        identity = _make_identity()
        with pytest.raises(ValueError, match="timezone"):
            RecoveryPreDispatchClaim.create(
                attempt_identity_digest=identity.identity_digest,
                hold_revision=1,
                claim_revision=1,
                idempotency_key="key-1",
                claimed_at=datetime(2026, 1, 1),
            )

    def test_reject_empty_idempotency_key(self) -> None:
        identity = _make_identity()
        with pytest.raises(ValueError, match="idempotency_key"):
            RecoveryPreDispatchClaim.create(
                attempt_identity_digest=identity.identity_digest,
                hold_revision=1,
                claim_revision=1,
                idempotency_key="",
                claimed_at=_NOW,
            )


class TestDispatchResult:
    def test_dispatched_outcome(self) -> None:
        identity = _make_identity()
        claim = RecoveryPreDispatchClaim.create(
            attempt_identity_digest=identity.identity_digest,
            hold_revision=1,
            claim_revision=1,
            idempotency_key="key-1",
            claimed_at=_NOW,
        )
        result = RecoveryDispatchResult.create(
            attempt_identity_digest=identity.identity_digest,
            claim_digest=claim.claim_digest,
            outcome=RecoveryDispatchOutcome.DISPATCHED,
            provider_receipt_digest=_RECEIPT_DIGEST,
            recorded_at=_NOW,
        )
        assert result.outcome == "dispatched"
        assert result.execution_authority is False

    def test_not_invoked_outcome(self) -> None:
        identity = _make_identity()
        claim = RecoveryPreDispatchClaim.create(
            attempt_identity_digest=identity.identity_digest,
            hold_revision=1,
            claim_revision=1,
            idempotency_key="key-1",
            claimed_at=_NOW,
        )
        result = RecoveryDispatchResult.create(
            attempt_identity_digest=identity.identity_digest,
            claim_digest=claim.claim_digest,
            outcome=RecoveryDispatchOutcome.NOT_INVOKED,
            provider_receipt_digest=None,
            recorded_at=_NOW,
        )
        assert result.outcome == "not_invoked"
        assert result.provider_receipt_digest is None

    def test_in_doubt_outcome(self) -> None:
        identity = _make_identity()
        claim = RecoveryPreDispatchClaim.create(
            attempt_identity_digest=identity.identity_digest,
            hold_revision=1,
            claim_revision=1,
            idempotency_key="key-1",
            claimed_at=_NOW,
        )
        result = RecoveryDispatchResult.create(
            attempt_identity_digest=identity.identity_digest,
            claim_digest=claim.claim_digest,
            outcome=RecoveryDispatchOutcome.IN_DOUBT,
            provider_receipt_digest=None,
            recorded_at=_NOW,
        )
        assert result.outcome == "in_doubt"

    def test_reject_invalid_outcome(self) -> None:
        identity = _make_identity()
        claim = RecoveryPreDispatchClaim.create(
            attempt_identity_digest=identity.identity_digest,
            hold_revision=1,
            claim_revision=1,
            idempotency_key="key-1",
            claimed_at=_NOW,
        )
        with pytest.raises(ValueError, match="outcome"):
            RecoveryDispatchResult.create(
                attempt_identity_digest=identity.identity_digest,
                claim_digest=claim.claim_digest,
                outcome="fabricated",
                provider_receipt_digest=None,
                recorded_at=_NOW,
            )

    def test_result_digest_deterministic(self) -> None:
        identity = _make_identity()
        claim = RecoveryPreDispatchClaim.create(
            attempt_identity_digest=identity.identity_digest,
            hold_revision=1,
            claim_revision=1,
            idempotency_key="key-1",
            claimed_at=_NOW,
        )
        a = RecoveryDispatchResult.create(
            attempt_identity_digest=identity.identity_digest,
            claim_digest=claim.claim_digest,
            outcome=RecoveryDispatchOutcome.DISPATCHED,
            provider_receipt_digest=_RECEIPT_DIGEST,
            recorded_at=_NOW,
        )
        b = RecoveryDispatchResult.create(
            attempt_identity_digest=identity.identity_digest,
            claim_digest=claim.claim_digest,
            outcome=RecoveryDispatchOutcome.DISPATCHED,
            provider_receipt_digest=_RECEIPT_DIGEST,
            recorded_at=_NOW,
        )
        assert a.result_digest == b.result_digest


class TestApprovalEvidence:
    def test_separate_approval(self) -> None:
        identity = _make_identity()
        evidence = RecoveryApprovalEvidence.create(
            attempt_identity_digest=identity.identity_digest,
            approval_digest=_APPROVAL_DIGEST,
            approved_at=_NOW,
            approver_identity="approver@example.com",
        )
        assert evidence.execution_authority is False
        assert evidence.approval_authority is False

    def test_reject_authority(self) -> None:
        identity = _make_identity()
        evidence = RecoveryApprovalEvidence.create(
            attempt_identity_digest=identity.identity_digest,
            approval_digest=_APPROVAL_DIGEST,
            approved_at=_NOW,
            approver_identity="approver@example.com",
        )
        with pytest.raises(ValueError, match="authority"):
            RecoveryApprovalEvidence(
                attempt_identity_digest=evidence.attempt_identity_digest,
                approval_digest=evidence.approval_digest,
                approved_at=evidence.approved_at,
                approver_identity=evidence.approver_identity,
                evidence_digest=evidence.evidence_digest,
                execution_authority=True,  # type: ignore[arg-type]
            )

    def test_reject_tampered_evidence_digest(self) -> None:
        identity = _make_identity()
        evidence = RecoveryApprovalEvidence.create(
            attempt_identity_digest=identity.identity_digest,
            approval_digest=_APPROVAL_DIGEST,
            approved_at=_NOW,
            approver_identity="approver@example.com",
        )

        with pytest.raises(ValueError, match="digest mismatched"):
            RecoveryApprovalEvidence(
                attempt_identity_digest=evidence.attempt_identity_digest,
                approval_digest=evidence.approval_digest,
                approved_at=evidence.approved_at,
                approver_identity=evidence.approver_identity,
                evidence_digest="sha256:" + "0" * 64,
            )


class TestSafeguardEvidence:
    def test_separate_safeguard(self) -> None:
        identity = _make_identity()
        evidence = RecoverySafeguardEvidence.create(
            attempt_identity_digest=identity.identity_digest,
            safeguard_bundle_digest=_SAFEGUARD_DIGEST,
            completed_at=_NOW,
        )
        assert evidence.execution_authority is False

    def test_reject_authority(self) -> None:
        identity = _make_identity()
        evidence = RecoverySafeguardEvidence.create(
            attempt_identity_digest=identity.identity_digest,
            safeguard_bundle_digest=_SAFEGUARD_DIGEST,
            completed_at=_NOW,
        )
        with pytest.raises(ValueError, match="authority"):
            RecoverySafeguardEvidence(
                attempt_identity_digest=evidence.attempt_identity_digest,
                safeguard_bundle_digest=evidence.safeguard_bundle_digest,
                completed_at=evidence.completed_at,
                evidence_digest=evidence.evidence_digest,
                execution_authority=True,  # type: ignore[arg-type]
            )

    def test_reject_tampered_evidence_digest(self) -> None:
        identity = _make_identity()
        evidence = RecoverySafeguardEvidence.create(
            attempt_identity_digest=identity.identity_digest,
            safeguard_bundle_digest=_SAFEGUARD_DIGEST,
            completed_at=_NOW,
        )

        with pytest.raises(ValueError, match="digest mismatched"):
            RecoverySafeguardEvidence(
                attempt_identity_digest=evidence.attempt_identity_digest,
                safeguard_bundle_digest=evidence.safeguard_bundle_digest,
                completed_at=evidence.completed_at,
                evidence_digest="sha256:" + "0" * 64,
            )


class TestIdempotencyKey:
    def test_stable(self) -> None:
        identity = _make_identity()
        a = recovery_attempt_idempotency_key(identity)
        b = recovery_attempt_idempotency_key(identity)
        assert a == b
        assert a.startswith("sha256:")

    def test_different_attempts(self) -> None:
        a = recovery_attempt_idempotency_key(_make_identity(attempt_number=1))
        b = recovery_attempt_idempotency_key(_make_identity(attempt_number=2))
        assert a != b


class TestPayloadSubstitution:
    """Payload digest substitution changes the identity and claim."""

    def test_different_payload_different_identity(self) -> None:
        a = RecoveryAttemptIdentity.create(
            process_id="process-1",
            failed_compensation_proposal_digest=_COMP_DIGEST,
            hold_revision=1,
            recovery_action_type="restart_pod",
            recovery_payload_digest=_PAYLOAD_DIGEST,
            target_digest=_TARGET_DIGEST,
            source_revision="commit:" + "0" * 40,
            attempt_number=1,
        )
        b = RecoveryAttemptIdentity.create(
            process_id="process-1",
            failed_compensation_proposal_digest=_COMP_DIGEST,
            hold_revision=1,
            recovery_action_type="restart_pod",
            recovery_payload_digest="sha256:" + "9" * 64,
            target_digest=_TARGET_DIGEST,
            source_revision="commit:" + "0" * 40,
            attempt_number=1,
        )
        assert a.identity_digest != b.identity_digest
