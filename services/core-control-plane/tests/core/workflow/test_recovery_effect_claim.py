"""Focused deterministic tests for recovery effect completion claims (#656)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.workflow.recovery_effect_claim import (
    CompletionClaimRejectionReason,
    EffectCompletionClaim,
    EffectEvidenceClass,
    EffectEvidenceRecord,
    FinalizedWatermark,
    is_current_success,
    supersede_claim,
    verify_effect_evidence,
)
from fdai_service_contracts.ontology_query import content_digest

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


def _make_claim(*, success: bool = True, generation: int = 1) -> EffectCompletionClaim:
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


def _make_evidence(
    *,
    authority_class: EffectEvidenceClass = EffectEvidenceClass.AUTHORITATIVE_EXTERNAL,
    observer_identity: str = "observer@monitor.example.com",
    synthetic: bool = False,
    completeness: bool = True,
    conflict_status: str = "none",
) -> EffectEvidenceRecord:
    digest = content_digest(
        {
            "observer_identity": observer_identity,
            "observer_authority_class": authority_class.value,
        }
    )
    return EffectEvidenceRecord(
        observer_identity=observer_identity,
        observer_authority_class=authority_class,
        purpose_version="1.0",
        method_version="1.0",
        event_time=_NOW - timedelta(minutes=1),
        recorded_time=_NOW,
        freshness_policy_seconds=300,
        completeness=completeness,
        provenance="external_monitor",
        conflict_status=conflict_status,
        synthetic=synthetic,
        evidence_digest=digest,
    )


class TestEffectCompletionClaim:
    def test_create_success(self) -> None:
        claim = _make_claim(success=True)
        assert claim.success is True
        assert claim.generation == 1
        assert claim.superseded_by is None
        assert claim.execution_authority is False
        assert claim.claim_digest.startswith("sha256:")

    def test_create_non_success(self) -> None:
        claim = _make_claim(success=False)
        assert claim.success is False
        assert claim.execution_authority is False

    def test_deterministic_digest(self) -> None:
        a = _make_claim()
        b = _make_claim()
        assert a.claim_digest == b.claim_digest

    def test_different_generation_different_digest(self) -> None:
        a = _make_claim(generation=1)
        b = _make_claim(generation=2)
        assert a.claim_digest != b.claim_digest

    def test_reject_execution_authority(self) -> None:
        claim = _make_claim()
        with pytest.raises(ValueError, match="execution authority"):
            EffectCompletionClaim(
                attempt_identity_digest=claim.attempt_identity_digest,
                action_digest=claim.action_digest,
                safeguard_bundle_digest=claim.safeguard_bundle_digest,
                provider_receipt_digest=claim.provider_receipt_digest,
                target_digest=claim.target_digest,
                expected_effect_digest=claim.expected_effect_digest,
                approved_envelope_digest=claim.approved_envelope_digest,
                source_revision=claim.source_revision,
                evidence_window_start=claim.evidence_window_start,
                evidence_window_end=claim.evidence_window_end,
                effect_evidence_digest=claim.effect_evidence_digest,
                validity_start=claim.validity_start,
                validity_end=claim.validity_end,
                watermark_set_digest=claim.watermark_set_digest,
                hold_revision=claim.hold_revision,
                admission_digest=claim.admission_digest,
                success=claim.success,
                generation=claim.generation,
                superseded_by=claim.superseded_by,
                claim_digest=claim.claim_digest,
                execution_authority=True,  # type: ignore[arg-type]
            )

    def test_reject_zero_generation(self) -> None:
        with pytest.raises(ValueError, match="generation"):
            _make_claim(generation=0)

    def test_reject_tampered_digest(self) -> None:
        claim = _make_claim()
        with pytest.raises(ValueError, match="mismatched"):
            EffectCompletionClaim(
                attempt_identity_digest=claim.attempt_identity_digest,
                action_digest=claim.action_digest,
                safeguard_bundle_digest=claim.safeguard_bundle_digest,
                provider_receipt_digest=claim.provider_receipt_digest,
                target_digest=claim.target_digest,
                expected_effect_digest=claim.expected_effect_digest,
                approved_envelope_digest=claim.approved_envelope_digest,
                source_revision=claim.source_revision,
                evidence_window_start=claim.evidence_window_start,
                evidence_window_end=claim.evidence_window_end,
                effect_evidence_digest=claim.effect_evidence_digest,
                validity_start=claim.validity_start,
                validity_end=claim.validity_end,
                watermark_set_digest=claim.watermark_set_digest,
                hold_revision=claim.hold_revision,
                admission_digest=claim.admission_digest,
                success=claim.success,
                generation=claim.generation,
                superseded_by=claim.superseded_by,
                claim_digest="sha256:" + "9" * 64,
            )


class TestSupersession:
    def test_supersede_changes_digest(self) -> None:
        claim = _make_claim()
        superseded = supersede_claim(claim, superseding_digest="sha256:" + "5" * 64)
        assert superseded.superseded_by == "sha256:" + "5" * 64
        assert superseded.claim_digest != claim.claim_digest

    def test_cannot_supersede_twice(self) -> None:
        claim = _make_claim()
        superseded = supersede_claim(claim, superseding_digest="sha256:" + "5" * 64)
        with pytest.raises(ValueError, match="already superseded"):
            supersede_claim(superseded, superseding_digest="sha256:" + "6" * 64)

    def test_reject_invalid_superseding_digest(self) -> None:
        claim = _make_claim()
        with pytest.raises(ValueError, match="superseding_digest"):
            supersede_claim(claim, superseding_digest="bad")


class TestIsCurrentSuccess:
    def test_current_success(self) -> None:
        claim = _make_claim(success=True)
        assert is_current_success(claim, now=_NOW + timedelta(minutes=30)) is True

    def test_non_success(self) -> None:
        claim = _make_claim(success=False)
        assert is_current_success(claim, now=_NOW + timedelta(minutes=30)) is False

    def test_expired(self) -> None:
        claim = _make_claim(success=True)
        assert is_current_success(claim, now=_NOW + timedelta(hours=2)) is False

    def test_not_yet_valid(self) -> None:
        claim = _make_claim(success=True)
        assert is_current_success(claim, now=_NOW - timedelta(minutes=10)) is False

    def test_superseded(self) -> None:
        claim = _make_claim(success=True)
        superseded = supersede_claim(claim, superseding_digest="sha256:" + "5" * 64)
        assert is_current_success(superseded, now=_NOW + timedelta(minutes=30)) is False

    def test_naive_datetime_returns_false(self) -> None:
        claim = _make_claim(success=True)
        assert is_current_success(claim, now=datetime(2026, 9, 11, 0, 30)) is False


class TestVerifyEffectEvidence:
    def test_eligible(self) -> None:
        evidence = _make_evidence()
        eligible, reasons = verify_effect_evidence(
            evidence=evidence,
            executor_identity="executor@example.com",
            provider_identity="provider@cloud.example.com",
        )
        assert eligible is True
        assert reasons == ()

    def test_executor_controlled_provenance(self) -> None:
        evidence = _make_evidence(authority_class=EffectEvidenceClass.EXECUTOR_CONTROLLED)
        eligible, reasons = verify_effect_evidence(
            evidence=evidence,
            executor_identity="executor@example.com",
            provider_identity="provider@cloud.example.com",
        )
        assert eligible is False
        assert CompletionClaimRejectionReason.EVIDENCE_INELIGIBLE in reasons

    def test_identity_separation_executor(self) -> None:
        evidence = _make_evidence(observer_identity="executor@example.com")
        eligible, reasons = verify_effect_evidence(
            evidence=evidence,
            executor_identity="executor@example.com",
            provider_identity="provider@cloud.example.com",
        )
        assert eligible is False
        assert CompletionClaimRejectionReason.IDENTITY_SEPARATION_VIOLATION in reasons

    def test_identity_separation_provider(self) -> None:
        evidence = _make_evidence(observer_identity="provider@cloud.example.com")
        eligible, reasons = verify_effect_evidence(
            evidence=evidence,
            executor_identity="executor@example.com",
            provider_identity="provider@cloud.example.com",
        )
        assert eligible is False
        assert CompletionClaimRejectionReason.IDENTITY_SEPARATION_VIOLATION in reasons

    def test_synthetic_evidence_rejected(self) -> None:
        with pytest.raises(ValueError, match="synthetic"):
            _make_evidence(synthetic=True)

    def test_incomplete_evidence(self) -> None:
        evidence = _make_evidence(completeness=False)
        eligible, reasons = verify_effect_evidence(
            evidence=evidence,
            executor_identity="executor@example.com",
            provider_identity="provider@cloud.example.com",
        )
        assert eligible is False
        assert CompletionClaimRejectionReason.FINALITY_INCOMPLETE in reasons

    def test_conflicting_evidence(self) -> None:
        evidence = _make_evidence(conflict_status="conflicting")
        eligible, reasons = verify_effect_evidence(
            evidence=evidence,
            executor_identity="executor@example.com",
            provider_identity="provider@cloud.example.com",
        )
        assert eligible is False
        assert CompletionClaimRejectionReason.EVIDENCE_INELIGIBLE in reasons

    def test_stale_evidence_class(self) -> None:
        evidence = _make_evidence(authority_class=EffectEvidenceClass.STALE)
        eligible, reasons = verify_effect_evidence(
            evidence=evidence,
            executor_identity="executor@example.com",
            provider_identity="provider@cloud.example.com",
        )
        assert eligible is False

    def test_missing_evidence_class(self) -> None:
        evidence = _make_evidence(authority_class=EffectEvidenceClass.MISSING)
        eligible, reasons = verify_effect_evidence(
            evidence=evidence,
            executor_identity="executor@example.com",
            provider_identity="provider@cloud.example.com",
        )
        assert eligible is False

    def test_out_of_envelope(self) -> None:
        evidence = _make_evidence(authority_class=EffectEvidenceClass.OUT_OF_ENVELOPE)
        eligible, reasons = verify_effect_evidence(
            evidence=evidence,
            executor_identity="executor@example.com",
            provider_identity="provider@cloud.example.com",
        )
        assert eligible is False

    def test_censored_evidence(self) -> None:
        evidence = _make_evidence(authority_class=EffectEvidenceClass.CENSORED)
        eligible, reasons = verify_effect_evidence(
            evidence=evidence,
            executor_identity="executor@example.com",
            provider_identity="provider@cloud.example.com",
        )
        assert eligible is False


class TestEffectReceiptSubstitution:
    """Effect-receipt substitution changes the claim digest."""

    def test_different_receipt_different_claim(self) -> None:
        a = EffectCompletionClaim.create_success(
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
            generation=1,
        )
        b = EffectCompletionClaim.create_success(
            attempt_identity_digest=_ATTEMPT_DIGEST,
            action_digest=_ACTION_DIGEST,
            safeguard_bundle_digest=_SAFEGUARD_DIGEST,
            provider_receipt_digest="sha256:" + "9" * 64,
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
            generation=1,
        )
        assert a.claim_digest != b.claim_digest


class TestFinalizedWatermark:
    def test_create(self) -> None:
        wm = FinalizedWatermark(
            source_id="monitor-1",
            watermark=_NOW,
            final=True,
            watermark_digest="sha256:" + "7" * 64,
        )
        assert wm.final is True

    def test_reject_empty_source(self) -> None:
        with pytest.raises(ValueError, match="source_id"):
            FinalizedWatermark(
                source_id="",
                watermark=_NOW,
                final=True,
                watermark_digest="sha256:" + "7" * 64,
            )

    def test_reject_naive_watermark(self) -> None:
        with pytest.raises(ValueError, match="timezone"):
            FinalizedWatermark(
                source_id="monitor-1",
                watermark=datetime(2026, 1, 1),
                final=True,
                watermark_digest="sha256:" + "7" * 64,
            )

    def test_reject_bad_digest(self) -> None:
        with pytest.raises(ValueError, match="digest"):
            FinalizedWatermark(
                source_id="monitor-1",
                watermark=_NOW,
                final=True,
                watermark_digest="bad",
            )
