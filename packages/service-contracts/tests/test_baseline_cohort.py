"""Governed baseline and treatment cohort claim-eligibility tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai_service_contracts.baseline_cohort import (
    MINIMUM_COHORT_SAMPLE_SIZE,
    BaselineTreatmentCohortReceipt,
    CohortArm,
    CohortArtifactOrigin,
    CohortClaimRejectionReason,
    CohortClaimRequirement,
    baseline_treatment_cohort_receipt_digest,
    evaluate_cohort_claim,
    missing_cohort_claim,
)
from fdai_service_contracts.decision_evidence import (
    DecisionCriticalEvidenceReceipt,
    EvidenceConflictStatus,
    decision_critical_evidence_receipt_digest,
)
from pydantic import ValidationError

SCENARIO_SET_DIGEST = "sha256:" + "1" * 64
BASELINE_REPORT_DIGEST = "sha256:" + "2" * 64
BASELINE_PROVENANCE_DIGEST = "sha256:" + "3" * 64
TREATMENT_REPORT_DIGEST = "sha256:" + "4" * 64
TREATMENT_PROVENANCE_DIGEST = "sha256:" + "5" * 64
AUTH_DIGEST = "sha256:" + "6" * 64
POLICY_DIGEST = "sha256:" + "7" * 64
COMPLETENESS_DIGEST = "sha256:" + "8" * 64
CONFLICT_DIGEST = "sha256:" + "9" * 64
REVISION = "git:0123456789abcdef0123456789abcdef01234567"
SCENARIO_SET = "v2026.07"
NOW = datetime(2026, 9, 1, tzinfo=UTC)
FRESHNESS_SECONDS = 86_400


def _evidence_receipt(
    *,
    report_digest: str,
    provenance_digest: str,
    synthetic: bool = False,
    source_revision: str = REVISION,
    scope_digest: str = SCENARIO_SET_DIGEST,
    method_id: str = "frozen-scenario-replay",
) -> DecisionCriticalEvidenceReceipt:
    values: dict[str, Any] = {
        "schema_version": "1.0.0",
        "authority_class": "deployment_observation",
        "source_identity": "principal:sre-cohort-runner",
        "authentication_evidence_digest": AUTH_DIGEST,
        "scope_digest": scope_digest,
        "purpose_id": "sre-claim-cohort",
        "producer_id": "cohort-runner",
        "producer_version": "1.0.0",
        "method_id": method_id,
        "method_version": "1.0.0",
        "source_revision": source_revision,
        "evidence_digest": report_digest,
        "provenance_digest": provenance_digest,
        "event_at": NOW - timedelta(hours=2),
        "evidence_cutoff": NOW - timedelta(hours=1),
        "recorded_at": NOW - timedelta(minutes=30),
        "fresh_until": NOW - timedelta(hours=1) + timedelta(seconds=FRESHNESS_SECONDS),
        "freshness_policy_id": "cohort-daily",
        "freshness_policy_version": "1.0.0",
        "freshness_policy_digest": POLICY_DIGEST,
        "freshness_ceiling_seconds": FRESHNESS_SECONDS,
        "completeness_basis_points": 10_000,
        "completeness_evidence_digest": COMPLETENESS_DIGEST,
        "conflict_status": EvidenceConflictStatus.CLEAR,
        "conflict_evidence_digest": CONFLICT_DIGEST,
        "conflict_evidence_digests": (),
        "synthetic": synthetic,
        "execution_authority": False,
    }
    values["receipt_digest"] = decision_critical_evidence_receipt_digest(**values)
    return DecisionCriticalEvidenceReceipt.model_validate(values)


def _arm(
    arm: CohortArm,
    *,
    report_digest: str,
    provenance_digest: str,
    sample_count: int = MINIMUM_COHORT_SAMPLE_SIZE,
    synthetic: bool = False,
    metrics_complete: bool = True,
    provenance_complete: bool = True,
    guard_basis_points: int = 0,
    scenario_set_version: str = SCENARIO_SET,
    fdai_revision: str = REVISION,
    evidence: DecisionCriticalEvidenceReceipt | None = None,
    metric_sample_count: int | None = None,
) -> dict[str, Any]:
    metric_samples = sample_count if metric_sample_count is None else metric_sample_count
    return {
        "arm": arm,
        "scenario_set_version": scenario_set_version,
        "scenario_set_digest": SCENARIO_SET_DIGEST,
        "fdai_revision": fdai_revision,
        "report_digest": report_digest,
        "provenance_digest": provenance_digest,
        "sample_count": sample_count,
        "synthetic": synthetic,
        "metrics_complete": metrics_complete,
        "provenance_complete": provenance_complete,
        "metrics": (
            {
                "metric_id": "auto_resolution_rate",
                "absolute_value": 0.4,
                "sample_size": metric_samples,
                "lower_bound": 0.25,
                "upper_bound": 0.57,
            },
            {
                "metric_id": "human_touchpoints_per_100_events",
                "absolute_value": 60.0,
                "sample_size": metric_samples,
                "lower_bound": 43.0,
                "upper_bound": 75.0,
            },
        ),
        "guards": (
            {
                "guard_id": "policy_violation_escape_rate",
                "observed_basis_points": guard_basis_points,
                "sample_size": sample_count,
                "breached": guard_basis_points > 0,
            },
            {
                "guard_id": "rollback_rate",
                "observed_basis_points": 0,
                "sample_size": sample_count,
                "breached": False,
            },
        ),
        "evidence_receipt": evidence
        or _evidence_receipt(
            report_digest=report_digest,
            provenance_digest=provenance_digest,
            synthetic=synthetic,
            source_revision=fdai_revision,
        ),
    }


def _receipt(
    *,
    origin: CohortArtifactOrigin = CohortArtifactOrigin.GOVERNED_EXTERNAL,
    baseline: dict[str, Any] | None = None,
    treatment: dict[str, Any] | None = None,
    scenario_set_version: str = SCENARIO_SET,
    fdai_revision: str = REVISION,
) -> BaselineTreatmentCohortReceipt:
    values: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cohort_id": "sre-v2026.07-cohort",
        "scenario_set_version": scenario_set_version,
        "scenario_set_digest": SCENARIO_SET_DIGEST,
        "fdai_revision": fdai_revision,
        "artifact_origin": origin,
        "baseline": baseline
        or _arm(
            CohortArm.BASELINE,
            report_digest=BASELINE_REPORT_DIGEST,
            provenance_digest=BASELINE_PROVENANCE_DIGEST,
        ),
        "treatment": treatment
        or _arm(
            CohortArm.TREATMENT,
            report_digest=TREATMENT_REPORT_DIGEST,
            provenance_digest=TREATMENT_PROVENANCE_DIGEST,
        ),
        "evidence_cutoff": NOW - timedelta(hours=1),
        "execution_authority": False,
    }
    values["receipt_digest"] = baseline_treatment_cohort_receipt_digest(**values)
    return BaselineTreatmentCohortReceipt.model_validate(values)


def _requirement(**overrides: Any) -> CohortClaimRequirement:
    evidence = {
        "allowed_authority_classes": ("deployment_observation",),
        "allowed_source_identities": ("principal:sre-cohort-runner",),
        "scope_digest": SCENARIO_SET_DIGEST,
        "purpose_id": "sre-claim-cohort",
        "producer_id": "cohort-runner",
        "producer_version": "1.0.0",
        "method_id": "frozen-scenario-replay",
        "method_version": "1.0.0",
        "source_revision": REVISION,
        "freshness_policy_digest": POLICY_DIGEST,
        "freshness_ceiling_seconds": FRESHNESS_SECONDS,
    }
    values: dict[str, Any] = {
        "scenario_set_version": SCENARIO_SET,
        "scenario_set_digest": SCENARIO_SET_DIGEST,
        "fdai_revision": REVISION,
        "required_metric_ids": ("auto_resolution_rate", "human_touchpoints_per_100_events"),
        "required_guard_ids": ("policy_violation_escape_rate", "rollback_rate"),
        "baseline_evidence": evidence,
        "treatment_evidence": evidence,
    }
    values.update(overrides)
    return CohortClaimRequirement.model_validate(values)


def _admitted(receipt: BaselineTreatmentCohortReceipt) -> frozenset[str]:
    return frozenset(
        {
            receipt.baseline.evidence_receipt.receipt_digest,
            receipt.treatment.evidence_receipt.receipt_digest,
        }
    )


def test_a_governed_admitted_cohort_is_claim_eligible() -> None:
    receipt = _receipt()

    assessment = evaluate_cohort_claim(
        receipt,
        _requirement(),
        evaluated_at=NOW,
        admitted_receipt_digests=_admitted(receipt),
    )

    assert assessment.claim_eligible is True
    assert assessment.rejection_reasons == ()
    assert assessment.receipt_digest == receipt.receipt_digest
    assert assessment.execution_authority is False
    assert tuple(arm.arm for arm in assessment.arms) == (CohortArm.BASELINE, CohortArm.TREATMENT)


def test_a_missing_receipt_fails_closed() -> None:
    assessment = missing_cohort_claim(evaluated_at=NOW)

    assert assessment.claim_eligible is False
    assert assessment.rejection_reasons == (CohortClaimRejectionReason.RECEIPT_MISSING,)
    assert assessment.receipt_digest is None
    assert evaluate_cohort_claim(None, _requirement(), evaluated_at=NOW) == assessment


def test_an_unadmitted_cohort_is_never_eligible() -> None:
    receipt = _receipt()

    assessment = evaluate_cohort_claim(receipt, _requirement(), evaluated_at=NOW)

    assert assessment.claim_eligible is False
    assert CohortClaimRejectionReason.EVIDENCE_NOT_ADMITTED in assessment.rejection_reasons


def test_a_repository_artifact_cannot_claim_eligibility() -> None:
    receipt = _receipt(origin=CohortArtifactOrigin.REPOSITORY)

    assessment = evaluate_cohort_claim(
        receipt,
        _requirement(),
        evaluated_at=NOW,
        admitted_receipt_digests=_admitted(receipt),
    )

    assert assessment.claim_eligible is False
    assert assessment.rejection_reasons == (CohortClaimRejectionReason.ARTIFACT_UNGOVERNED,)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"synthetic": True}, CohortClaimRejectionReason.SYNTHETIC),
        (
            {"sample_count": MINIMUM_COHORT_SAMPLE_SIZE - 1},
            CohortClaimRejectionReason.COHORT_UNDERSIZED,
        ),
        ({"metrics_complete": False}, CohortClaimRejectionReason.METRICS_INCOMPLETE),
        ({"provenance_complete": False}, CohortClaimRejectionReason.PROVENANCE_INCOMPLETE),
        ({"guard_basis_points": 1}, CohortClaimRejectionReason.GUARD_BREACHED),
        (
            {"metric_sample_count": MINIMUM_COHORT_SAMPLE_SIZE - 1},
            CohortClaimRejectionReason.CONFIDENCE_INTERVAL_INCOMPLETE,
        ),
    ],
)
def test_a_defective_treatment_arm_fails_closed(
    overrides: dict[str, Any],
    expected: CohortClaimRejectionReason,
) -> None:
    treatment = _arm(
        CohortArm.TREATMENT,
        report_digest=TREATMENT_REPORT_DIGEST,
        provenance_digest=TREATMENT_PROVENANCE_DIGEST,
        **overrides,
    )
    receipt = _receipt(treatment=treatment)

    assessment = evaluate_cohort_claim(
        receipt,
        _requirement(),
        evaluated_at=NOW,
        admitted_receipt_digests=_admitted(receipt),
    )

    assert assessment.claim_eligible is False
    assert expected in assessment.rejection_reasons
    treatment_assessment = next(arm for arm in assessment.arms if arm.arm is CohortArm.TREATMENT)
    assert expected in treatment_assessment.rejection_reasons


def test_a_report_digest_that_the_receipt_does_not_cover_fails_closed() -> None:
    unrelated = "sha256:" + "b" * 64
    treatment = _arm(
        CohortArm.TREATMENT,
        report_digest=TREATMENT_REPORT_DIGEST,
        provenance_digest=TREATMENT_PROVENANCE_DIGEST,
        evidence=_evidence_receipt(
            report_digest=unrelated,
            provenance_digest=TREATMENT_PROVENANCE_DIGEST,
        ),
    )
    receipt = _receipt(treatment=treatment)

    assessment = evaluate_cohort_claim(
        receipt,
        _requirement(),
        evaluated_at=NOW,
        admitted_receipt_digests=_admitted(receipt),
    )

    assert assessment.claim_eligible is False
    assert CohortClaimRejectionReason.REPORT_DIGEST_MISMATCH in assessment.rejection_reasons


def test_a_mixed_revision_cohort_fails_closed() -> None:
    other_revision = "git:fedcba9876543210fedcba9876543210fedcba98"
    treatment = _arm(
        CohortArm.TREATMENT,
        report_digest=TREATMENT_REPORT_DIGEST,
        provenance_digest=TREATMENT_PROVENANCE_DIGEST,
        fdai_revision=other_revision,
    )
    receipt = _receipt(treatment=treatment)

    assessment = evaluate_cohort_claim(
        receipt,
        _requirement(),
        evaluated_at=NOW,
        admitted_receipt_digests=_admitted(receipt),
    )

    assert assessment.claim_eligible is False
    assert CohortClaimRejectionReason.REVISION_MISMATCH in assessment.rejection_reasons


def test_a_different_frozen_set_fails_closed() -> None:
    receipt = _receipt()

    assessment = evaluate_cohort_claim(
        receipt,
        _requirement(scenario_set_version="v2026.08"),
        evaluated_at=NOW,
        admitted_receipt_digests=_admitted(receipt),
    )

    assert assessment.claim_eligible is False
    assert CohortClaimRejectionReason.SCENARIO_SET_MISMATCH in assessment.rejection_reasons


def test_stale_evidence_is_rejected_by_the_shared_preflight() -> None:
    receipt = _receipt()

    assessment = evaluate_cohort_claim(
        receipt,
        _requirement(),
        evaluated_at=NOW + timedelta(days=3),
        admitted_receipt_digests=_admitted(receipt),
    )

    assert assessment.claim_eligible is False
    assert CohortClaimRejectionReason.EVIDENCE_PREFLIGHT_REJECTED in assessment.rejection_reasons
    baseline = next(arm for arm in assessment.arms if arm.arm is CohortArm.BASELINE)
    assert baseline.evidence_preflight is not None
    assert baseline.evidence_preflight.eligible_for_verification is False


def test_the_minimum_sample_size_cannot_be_weakened() -> None:
    with pytest.raises(ValidationError):
        _requirement(minimum_sample_size=MINIMUM_COHORT_SAMPLE_SIZE - 1)


def test_a_requirement_MUST_pin_the_cohort_revision_and_frozen_set() -> None:
    with pytest.raises(ValidationError, match="MUST pin the cohort revision"):
        _requirement(fdai_revision="git:1111111111111111111111111111111111111111")


def test_a_tampered_cohort_receipt_digest_is_rejected() -> None:
    receipt = _receipt()
    payload = receipt.model_dump(mode="json")
    payload["cohort_id"] = "sre-v2026.07-other"

    with pytest.raises(ValidationError, match="digest does not match"):
        BaselineTreatmentCohortReceipt.model_validate(payload)


def test_an_arm_MUST_carry_ordered_unique_measures() -> None:
    treatment = _arm(
        CohortArm.TREATMENT,
        report_digest=TREATMENT_REPORT_DIGEST,
        provenance_digest=TREATMENT_PROVENANCE_DIGEST,
    )
    treatment["metrics"] = tuple(reversed(treatment["metrics"]))

    with pytest.raises(ValidationError, match="unique and ordered"):
        _receipt(treatment=treatment)


def test_a_guard_MUST_declare_a_zero_threshold_breach_truthfully() -> None:
    treatment = _arm(
        CohortArm.TREATMENT,
        report_digest=TREATMENT_REPORT_DIGEST,
        provenance_digest=TREATMENT_PROVENANCE_DIGEST,
    )
    treatment["guards"] = (
        {
            "guard_id": "policy_violation_escape_rate",
            "observed_basis_points": 25,
            "sample_size": MINIMUM_COHORT_SAMPLE_SIZE,
            "breached": False,
        },
    )

    with pytest.raises(ValidationError, match="breach does not match"):
        _receipt(treatment=treatment)
