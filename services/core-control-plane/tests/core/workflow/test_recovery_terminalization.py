"""Focused deterministic tests for recovery terminalization (#658)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.workflow.recovery_effect_claim import (
    EffectCompletionClaim,
    supersede_claim,
)
from fdai.core.workflow.recovery_terminalization import (
    CompletionOutboxEntry,
    OutboxDeliveryState,
    RecoveryCompletionDigest,
    ReleaseReceiptLookup,
    TerminalTransitionRejection,
    check_replay_idempotent,
    validate_terminal_preconditions,
)

_NOW = datetime(2026, 9, 11, 0, 0, tzinfo=UTC)
_ATTEMPT_DIGEST = "sha256:" + "a" * 64
_ACTION_DIGEST = "sha256:" + "b" * 64
_SAFEGUARD_DIGEST = "sha256:" + "c" * 64
_RECEIPT_DIGEST = "sha256:" + "d" * 64
_TARGET_DIGEST = "sha256:" + "e" * 64
_EFFECT_DIGEST = "sha256:" + "f" * 64
_ENVELOPE_DIGEST = "sha256:" + "1" * 64
_EVIDENCE_DIGEST = "sha256:" + "2" * 64
_WATERMARK_DIGEST = "sha256:" + "3" * 64
_ADMISSION_DIGEST = "sha256:" + "4" * 64
_RELEASE_RECEIPT_DIGEST = "sha256:" + "5" * 64
_EVENT_DIGEST = "sha256:" + "6" * 64
_AUDIT_DIGEST = "sha256:" + "7" * 64


def _make_claim(*, generation: int = 1, success: bool = True) -> EffectCompletionClaim:
    factory = (
        EffectCompletionClaim.create_success
        if success
        else EffectCompletionClaim.create_non_success
    )
    return factory(
        attempt_identity_digest=_ATTEMPT_DIGEST,
        action_digest=_ACTION_DIGEST,
        safeguard_bundle_digest=_SAFEGUARD_DIGEST,
        provider_receipt_digest=_RECEIPT_DIGEST,
        target_digest=_TARGET_DIGEST,
        expected_effect_digest=_EFFECT_DIGEST,
        approved_envelope_digest=_ENVELOPE_DIGEST,
        source_revision="commit:" + "0" * 40,
        evidence_window_start=_NOW - timedelta(minutes=5),
        evidence_window_end=_NOW,
        effect_evidence_digest=_EVIDENCE_DIGEST,
        validity_start=_NOW,
        validity_end=_NOW + timedelta(hours=1),
        watermark_set_digest=_WATERMARK_DIGEST,
        hold_revision=1,
        admission_digest=_ADMISSION_DIGEST,
        generation=generation,
    )


class TestRecoveryCompletionDigest:
    def test_create_valid(self) -> None:
        cd = RecoveryCompletionDigest.create(
            process_id="process-1",
            saga_id="saga-1",
            expected_process_revision=5,
            recovery_attempt_digest=_ATTEMPT_DIGEST,
            effect_claim_generation=1,
            effect_claim_digest=_RECEIPT_DIGEST,
            release_receipt_digest=_RELEASE_RECEIPT_DIGEST,
            terminal_event_digest=_EVENT_DIGEST,
            audit_payload_digest=_AUDIT_DIGEST,
        )
        assert cd.resulting_process_revision == 6
        assert cd.execution_authority is False
        assert cd.completion_digest.startswith("sha256:")

    def test_deterministic(self) -> None:
        a = RecoveryCompletionDigest.create(
            process_id="process-1",
            saga_id="saga-1",
            expected_process_revision=5,
            recovery_attempt_digest=_ATTEMPT_DIGEST,
            effect_claim_generation=1,
            effect_claim_digest=_RECEIPT_DIGEST,
            release_receipt_digest=_RELEASE_RECEIPT_DIGEST,
            terminal_event_digest=_EVENT_DIGEST,
            audit_payload_digest=_AUDIT_DIGEST,
        )
        b = RecoveryCompletionDigest.create(
            process_id="process-1",
            saga_id="saga-1",
            expected_process_revision=5,
            recovery_attempt_digest=_ATTEMPT_DIGEST,
            effect_claim_generation=1,
            effect_claim_digest=_RECEIPT_DIGEST,
            release_receipt_digest=_RELEASE_RECEIPT_DIGEST,
            terminal_event_digest=_EVENT_DIGEST,
            audit_payload_digest=_AUDIT_DIGEST,
        )
        assert a.completion_digest == b.completion_digest

    def test_reject_revision_mismatch(self) -> None:
        cd = RecoveryCompletionDigest.create(
            process_id="process-1",
            saga_id="saga-1",
            expected_process_revision=5,
            recovery_attempt_digest=_ATTEMPT_DIGEST,
            effect_claim_generation=1,
            effect_claim_digest=_RECEIPT_DIGEST,
            release_receipt_digest=_RELEASE_RECEIPT_DIGEST,
            terminal_event_digest=_EVENT_DIGEST,
            audit_payload_digest=_AUDIT_DIGEST,
        )
        with pytest.raises(ValueError, match="resulting_process_revision"):
            RecoveryCompletionDigest(
                process_id=cd.process_id,
                saga_id=cd.saga_id,
                expected_process_revision=cd.expected_process_revision,
                resulting_process_revision=cd.expected_process_revision + 2,
                recovery_attempt_digest=cd.recovery_attempt_digest,
                effect_claim_generation=cd.effect_claim_generation,
                effect_claim_digest=cd.effect_claim_digest,
                release_receipt_digest=cd.release_receipt_digest,
                terminal_event_digest=cd.terminal_event_digest,
                audit_payload_digest=cd.audit_payload_digest,
                completion_digest=cd.completion_digest,
            )

    def test_reject_execution_authority(self) -> None:
        cd = RecoveryCompletionDigest.create(
            process_id="process-1",
            saga_id="saga-1",
            expected_process_revision=5,
            recovery_attempt_digest=_ATTEMPT_DIGEST,
            effect_claim_generation=1,
            effect_claim_digest=_RECEIPT_DIGEST,
            release_receipt_digest=_RELEASE_RECEIPT_DIGEST,
            terminal_event_digest=_EVENT_DIGEST,
            audit_payload_digest=_AUDIT_DIGEST,
        )
        with pytest.raises(ValueError, match="execution authority"):
            RecoveryCompletionDigest(
                process_id=cd.process_id,
                saga_id=cd.saga_id,
                expected_process_revision=cd.expected_process_revision,
                resulting_process_revision=cd.resulting_process_revision,
                recovery_attempt_digest=cd.recovery_attempt_digest,
                effect_claim_generation=cd.effect_claim_generation,
                effect_claim_digest=cd.effect_claim_digest,
                release_receipt_digest=cd.release_receipt_digest,
                terminal_event_digest=cd.terminal_event_digest,
                audit_payload_digest=cd.audit_payload_digest,
                completion_digest=cd.completion_digest,
                execution_authority=True,  # type: ignore[arg-type]
            )

    def test_reject_empty_process_id(self) -> None:
        with pytest.raises(ValueError, match="process_id"):
            RecoveryCompletionDigest.create(
                process_id="",
                saga_id="saga-1",
                expected_process_revision=5,
                recovery_attempt_digest=_ATTEMPT_DIGEST,
                effect_claim_generation=1,
                effect_claim_digest=_RECEIPT_DIGEST,
                release_receipt_digest=_RELEASE_RECEIPT_DIGEST,
                terminal_event_digest=_EVENT_DIGEST,
                audit_payload_digest=_AUDIT_DIGEST,
            )

    def test_reject_negative_expected_revision(self) -> None:
        with pytest.raises(ValueError, match="expected_process_revision"):
            RecoveryCompletionDigest.create(
                process_id="process-1",
                saga_id="saga-1",
                expected_process_revision=-1,
                recovery_attempt_digest=_ATTEMPT_DIGEST,
                effect_claim_generation=1,
                effect_claim_digest=_RECEIPT_DIGEST,
                release_receipt_digest=_RELEASE_RECEIPT_DIGEST,
                terminal_event_digest=_EVENT_DIGEST,
                audit_payload_digest=_AUDIT_DIGEST,
            )


class TestReleaseReceiptLookup:
    def test_create(self) -> None:
        lookup = ReleaseReceiptLookup.create(
            recovery_attempt_digest=_ATTEMPT_DIGEST,
            effect_claim_digest=_RECEIPT_DIGEST,
            hold_revision=1,
            release_receipt_digest=_RELEASE_RECEIPT_DIGEST,
        )
        assert lookup.lookup_digest.startswith("sha256:")

    def test_deterministic(self) -> None:
        a = ReleaseReceiptLookup.create(
            recovery_attempt_digest=_ATTEMPT_DIGEST,
            effect_claim_digest=_RECEIPT_DIGEST,
            hold_revision=1,
            release_receipt_digest=_RELEASE_RECEIPT_DIGEST,
        )
        b = ReleaseReceiptLookup.create(
            recovery_attempt_digest=_ATTEMPT_DIGEST,
            effect_claim_digest=_RECEIPT_DIGEST,
            hold_revision=1,
            release_receipt_digest=_RELEASE_RECEIPT_DIGEST,
        )
        assert a.lookup_digest == b.lookup_digest

    def test_reject_bad_digest(self) -> None:
        with pytest.raises(ValueError, match="release_receipt_digest"):
            ReleaseReceiptLookup.create(
                recovery_attempt_digest=_ATTEMPT_DIGEST,
                effect_claim_digest=_RECEIPT_DIGEST,
                hold_revision=1,
                release_receipt_digest="bad",
            )

    def test_reject_zero_hold_revision(self) -> None:
        with pytest.raises(ValueError, match="hold_revision"):
            ReleaseReceiptLookup.create(
                recovery_attempt_digest=_ATTEMPT_DIGEST,
                effect_claim_digest=_RECEIPT_DIGEST,
                hold_revision=0,
                release_receipt_digest=_RELEASE_RECEIPT_DIGEST,
            )


class TestCompletionOutbox:
    def test_create_pending(self) -> None:
        entry = CompletionOutboxEntry.create_pending(
            completion_digest=_RECEIPT_DIGEST,
            delivery_kind="process_event",
            payload_digest=_EVENT_DIGEST,
        )
        assert entry.delivery_state == OutboxDeliveryState.PENDING
        assert entry.attempt_count == 0
        assert entry.last_attempt_at is None

    def test_reject_invalid_kind(self) -> None:
        with pytest.raises(ValueError, match="delivery_kind"):
            CompletionOutboxEntry(
                completion_digest=_RECEIPT_DIGEST,
                delivery_kind="invalid",
                delivery_state=OutboxDeliveryState.PENDING,
                payload_digest=_EVENT_DIGEST,
                attempt_count=0,
                last_attempt_at=None,
                entry_digest=_AUDIT_DIGEST,
            )

    def test_reject_invalid_state(self) -> None:
        with pytest.raises(ValueError, match="delivery_state"):
            CompletionOutboxEntry(
                completion_digest=_RECEIPT_DIGEST,
                delivery_kind="process_event",
                delivery_state="bogus",
                payload_digest=_EVENT_DIGEST,
                attempt_count=0,
                last_attempt_at=None,
                entry_digest=_AUDIT_DIGEST,
            )


class TestValidateTerminalPreconditions:
    def test_all_valid(self) -> None:
        claim = _make_claim()
        eligible, reasons = validate_terminal_preconditions(
            claim=claim,
            hold_revision=1,
            fencing_generation=2,
            process_revision=5,
            expected_completion_digest=_RECEIPT_DIGEST,
            release_receipt_digest=_RELEASE_RECEIPT_DIGEST,
            now=_NOW + timedelta(minutes=30),
        )
        assert eligible is True
        assert reasons == ()

    def test_claim_not_current_success(self) -> None:
        claim = _make_claim(success=False)
        eligible, reasons = validate_terminal_preconditions(
            claim=claim,
            hold_revision=1,
            fencing_generation=2,
            process_revision=5,
            expected_completion_digest=_RECEIPT_DIGEST,
            release_receipt_digest=_RELEASE_RECEIPT_DIGEST,
            now=_NOW + timedelta(minutes=30),
        )
        assert eligible is False
        assert TerminalTransitionRejection.CLAIM_NOT_CURRENT_SUCCESS in reasons

    def test_claim_expired(self) -> None:
        claim = _make_claim()
        eligible, reasons = validate_terminal_preconditions(
            claim=claim,
            hold_revision=1,
            fencing_generation=2,
            process_revision=5,
            expected_completion_digest=_RECEIPT_DIGEST,
            release_receipt_digest=_RELEASE_RECEIPT_DIGEST,
            now=_NOW + timedelta(hours=2),
        )
        assert eligible is False
        assert TerminalTransitionRejection.CLAIM_EXPIRED in reasons

    def test_claim_revoked(self) -> None:
        claim = supersede_claim(_make_claim(), superseding_digest="sha256:" + "5" * 64)
        eligible, reasons = validate_terminal_preconditions(
            claim=claim,
            hold_revision=1,
            fencing_generation=2,
            process_revision=5,
            expected_completion_digest=_RECEIPT_DIGEST,
            release_receipt_digest=_RELEASE_RECEIPT_DIGEST,
            now=_NOW + timedelta(minutes=30),
        )
        assert eligible is False
        assert TerminalTransitionRejection.CLAIM_REVOKED in reasons

    def test_hold_revision_mismatch(self) -> None:
        claim = _make_claim()
        eligible, reasons = validate_terminal_preconditions(
            claim=claim,
            hold_revision=2,
            fencing_generation=3,
            process_revision=5,
            expected_completion_digest=_RECEIPT_DIGEST,
            release_receipt_digest=_RELEASE_RECEIPT_DIGEST,
            now=_NOW + timedelta(minutes=30),
        )
        assert eligible is False
        assert TerminalTransitionRejection.HOLD_REVISION_MISMATCH in reasons

    def test_fencing_generation_mismatch(self) -> None:
        claim = _make_claim()
        eligible, reasons = validate_terminal_preconditions(
            claim=claim,
            hold_revision=1,
            fencing_generation=5,
            process_revision=5,
            expected_completion_digest=_RECEIPT_DIGEST,
            release_receipt_digest=_RELEASE_RECEIPT_DIGEST,
            now=_NOW + timedelta(minutes=30),
        )
        assert eligible is False
        assert TerminalTransitionRejection.FENCING_GENERATION_MISMATCH in reasons

    def test_release_receipt_missing(self) -> None:
        claim = _make_claim()
        eligible, reasons = validate_terminal_preconditions(
            claim=claim,
            hold_revision=1,
            fencing_generation=2,
            process_revision=5,
            expected_completion_digest=_RECEIPT_DIGEST,
            release_receipt_digest=None,
            now=_NOW + timedelta(minutes=30),
        )
        assert eligible is False
        assert TerminalTransitionRejection.RELEASE_RECEIPT_MISSING in reasons


class TestReplayIdempotent:
    def test_matching_digest(self) -> None:
        assert (
            check_replay_idempotent(
                committed_completion_digest="sha256:" + "a" * 64,
                expected_completion_digest="sha256:" + "a" * 64,
            )
            is True
        )

    def test_no_committed_digest(self) -> None:
        assert (
            check_replay_idempotent(
                committed_completion_digest=None,
                expected_completion_digest="sha256:" + "a" * 64,
            )
            is False
        )

    def test_mismatch(self) -> None:
        assert (
            check_replay_idempotent(
                committed_completion_digest="sha256:" + "a" * 64,
                expected_completion_digest="sha256:" + "b" * 64,
            )
            is False
        )


class TestPayloadSubstitution:
    def test_different_event_digest_different_completion(self) -> None:
        a = RecoveryCompletionDigest.create(
            process_id="process-1",
            saga_id="saga-1",
            expected_process_revision=5,
            recovery_attempt_digest=_ATTEMPT_DIGEST,
            effect_claim_generation=1,
            effect_claim_digest=_RECEIPT_DIGEST,
            release_receipt_digest=_RELEASE_RECEIPT_DIGEST,
            terminal_event_digest=_EVENT_DIGEST,
            audit_payload_digest=_AUDIT_DIGEST,
        )
        b = RecoveryCompletionDigest.create(
            process_id="process-1",
            saga_id="saga-1",
            expected_process_revision=5,
            recovery_attempt_digest=_ATTEMPT_DIGEST,
            effect_claim_generation=1,
            effect_claim_digest=_RECEIPT_DIGEST,
            release_receipt_digest=_RELEASE_RECEIPT_DIGEST,
            terminal_event_digest="sha256:" + "8" * 64,
            audit_payload_digest=_AUDIT_DIGEST,
        )
        assert a.completion_digest != b.completion_digest
