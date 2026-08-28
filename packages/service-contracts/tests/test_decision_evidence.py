"""Decision-critical evidence envelope and live-eligibility tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
import pytest
from fdai_service_contracts.decision_evidence import (
    DecisionCriticalEvidenceReceipt,
    EvidenceConflictStatus,
    LiveEvidenceClaimRejectionReason,
    LiveEvidenceClaimRequirement,
    assess_live_evidence_claim,
    decision_critical_evidence_receipt_digest,
)
from fdai_service_contracts.schema import (
    ContractValidationError,
    JsonSchemaContractValidator,
    PackageResourceSchemaRegistry,
)
from pydantic import ValidationError

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
DIGEST_D = "sha256:" + "d" * 64
DIGEST_E = "sha256:" + "e" * 64
DIGEST_F = "sha256:" + "f" * 64
DIGEST_0 = "sha256:" + "0" * 64
NOW = datetime(2026, 8, 29, 0, 0, tzinfo=UTC)


def _receipt_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "schema_version": "1.0.0",
        "authority_class": "provider_observation",
        "source_identity": "principal:inventory-reader",
        "authentication_evidence_digest": DIGEST_A,
        "scope_digest": DIGEST_B,
        "purpose_id": "readiness",
        "producer_id": "inventory-observer",
        "producer_version": "1.2.0",
        "method_id": "resource-health-query",
        "method_version": "2.1.0",
        "source_revision": "api-version:2025-01-01",
        "evidence_digest": DIGEST_C,
        "provenance_digest": DIGEST_D,
        "event_at": NOW,
        "evidence_cutoff": NOW + timedelta(minutes=1),
        "recorded_at": NOW + timedelta(minutes=2),
        "fresh_until": NOW + timedelta(minutes=10),
        "freshness_policy_id": "readiness-ten-minute",
        "freshness_policy_version": "1.0.0",
        "freshness_policy_digest": DIGEST_E,
        "freshness_ceiling_seconds": 540,
        "completeness_basis_points": 10_000,
        "completeness_evidence_digest": DIGEST_F,
        "conflict_status": EvidenceConflictStatus.CLEAR,
        "conflict_evidence_digest": DIGEST_0,
        "conflict_evidence_digests": (),
        "synthetic": False,
        "execution_authority": False,
    }
    values.update(overrides)
    return values


def _receipt(**overrides: object) -> DecisionCriticalEvidenceReceipt:
    values = _receipt_values(**overrides)
    return DecisionCriticalEvidenceReceipt.model_validate(
        {
            **values,
            "receipt_digest": decision_critical_evidence_receipt_digest(**values),
        }
    )


def _requirement(**overrides: object) -> LiveEvidenceClaimRequirement:
    values: dict[str, object] = {
        "allowed_authority_classes": ("provider_observation",),
        "allowed_source_identities": ("principal:inventory-reader",),
        "scope_digest": DIGEST_B,
        "purpose_id": "readiness",
        "producer_id": "inventory-observer",
        "producer_version": "1.2.0",
        "method_id": "resource-health-query",
        "method_version": "2.1.0",
        "source_revision": "api-version:2025-01-01",
        "freshness_policy_digest": DIGEST_E,
        "freshness_ceiling_seconds": 540,
        "minimum_completeness_basis_points": 10_000,
    }
    values.update(overrides)
    return LiveEvidenceClaimRequirement.model_validate(values)


def test_receipt_digest_normalizes_equivalent_instants_to_utc() -> None:
    offset = timezone(timedelta(hours=9))
    shifted_values = _receipt_values(
        event_at=NOW.astimezone(offset),
        evidence_cutoff=(NOW + timedelta(minutes=1)).astimezone(offset),
        recorded_at=(NOW + timedelta(minutes=2)).astimezone(offset),
        fresh_until=(NOW + timedelta(minutes=10)).astimezone(offset),
    )

    assert decision_critical_evidence_receipt_digest(
        **shifted_values
    ) == decision_critical_evidence_receipt_digest(**_receipt_values())


def test_receipt_rejects_digest_tampering_and_naive_time() -> None:
    with pytest.raises(ValidationError, match="digest does not match"):
        DecisionCriticalEvidenceReceipt.model_validate(
            {**_receipt_values(), "receipt_digest": DIGEST_0}
        )

    with pytest.raises(ValidationError, match="timestamps MUST include a timezone"):
        decision_critical_evidence_receipt_digest(
            **_receipt_values(event_at=NOW.replace(tzinfo=None))
        )


def test_json_schema_requires_authentication_evidence() -> None:
    receipt = _receipt().model_dump(mode="json")
    receipt.pop("authentication_evidence_digest")
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())

    with pytest.raises(ContractValidationError, match="authentication_evidence_digest"):
        validator.validate("decision-critical-evidence", receipt)


def test_synthetic_evidence_never_reaches_live_verification() -> None:
    assessment = assess_live_evidence_claim(
        _receipt(synthetic=True),
        _requirement(),
        evaluated_at=NOW + timedelta(minutes=3),
    )

    assert assessment.eligible_for_verification is False
    assert assessment.rejection_reasons == (LiveEvidenceClaimRejectionReason.SYNTHETIC,)


def test_live_claim_preflight_accumulates_policy_and_evidence_failures() -> None:
    assessment = assess_live_evidence_claim(
        _receipt(
            authority_class="telemetry_observation",
            source_identity="principal:other",
            scope_digest=DIGEST_A,
            purpose_id="promotion",
            producer_id="other-producer",
            method_id="other-method",
            source_revision="api-version:other",
            freshness_policy_digest=DIGEST_F,
            freshness_ceiling_seconds=600,
            fresh_until=NOW + timedelta(minutes=11),
            completeness_basis_points=9_999,
            conflict_status=EvidenceConflictStatus.CONFLICTING,
            conflict_evidence_digests=(DIGEST_A,),
            synthetic=True,
        ),
        _requirement(),
        evaluated_at=NOW + timedelta(minutes=12),
    )

    assert assessment.eligible_for_verification is False
    expected_reasons = set(LiveEvidenceClaimRejectionReason) - {
        LiveEvidenceClaimRejectionReason.NOT_YET_RECORDED
    }
    assert assessment.rejection_reasons == tuple(sorted(expected_reasons, key=str))


def test_live_claim_preflight_requires_recorded_fresh_evidence() -> None:
    receipt = _receipt()

    not_recorded = assess_live_evidence_claim(
        receipt,
        _requirement(),
        evaluated_at=NOW + timedelta(minutes=1),
    )
    assert not_recorded.rejection_reasons == (LiveEvidenceClaimRejectionReason.NOT_YET_RECORDED,)

    fresh_at_boundary = assess_live_evidence_claim(
        receipt,
        _requirement(),
        evaluated_at=receipt.fresh_until,
    )
    assert fresh_at_boundary.eligible_for_verification is True
    assert fresh_at_boundary.rejection_reasons == ()

    stale = assess_live_evidence_claim(
        receipt,
        _requirement(),
        evaluated_at=receipt.fresh_until + timedelta(microseconds=1),
    )
    assert stale.rejection_reasons == (LiveEvidenceClaimRejectionReason.STALE,)


def test_conformant_claim_only_reaches_separate_verification() -> None:
    assessment = assess_live_evidence_claim(
        _receipt(),
        _requirement(),
        evaluated_at=NOW + timedelta(minutes=3),
    )

    assert assessment.eligible_for_verification is True
    assert assessment.rejection_reasons == ()
    assert "eligible" not in type(assessment).model_fields


def test_model_rejects_noncanonical_policy_and_conflicts() -> None:
    with pytest.raises(ValidationError, match="allowed authority classes"):
        _requirement(allowed_authority_classes=("telemetry_observation", "provider_observation"))

    values = _receipt_values(
        conflict_status=EvidenceConflictStatus.CONFLICTING,
        conflict_evidence_digests=(DIGEST_B, DIGEST_A),
    )
    with pytest.raises(ValidationError, match="conflict evidence digests"):
        decision_critical_evidence_receipt_digest(**values)


def test_schema_and_model_accept_the_same_canonical_receipt() -> None:
    receipt = _receipt()
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())

    validator.validate("decision-critical-evidence", receipt.model_dump(mode="json"))
    restored = DecisionCriticalEvidenceReceipt.model_validate(receipt.model_dump(mode="json"))

    assert restored == receipt


def test_registered_boundary_applies_semantic_receipt_validation() -> None:
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    reversed_time = _receipt().model_dump(mode="json")
    reversed_time["recorded_at"] = (NOW - timedelta(minutes=1)).isoformat()

    with pytest.raises(ContractValidationError, match="cutoff MUST NOT exceed recorded time"):
        validator.validate("decision-critical-evidence", reversed_time)

    fabricated_digest = _receipt().model_dump(mode="json")
    fabricated_digest["receipt_digest"] = DIGEST_0
    with pytest.raises(ContractValidationError, match="digest does not match"):
        validator.validate("decision-critical-evidence", fabricated_digest)

    descending_conflicts = _receipt(
        conflict_status=EvidenceConflictStatus.CONFLICTING,
        conflict_evidence_digests=(DIGEST_A,),
    ).model_dump(mode="json")
    descending_conflicts["conflict_evidence_digests"] = [DIGEST_B, DIGEST_A]
    with pytest.raises(ContractValidationError, match="conflict evidence digests"):
        validator.validate("decision-critical-evidence", descending_conflicts)
