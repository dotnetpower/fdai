"""Admission-bound cohort claim tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.measurement.baseline_cohort_claim import (
    admitted_cohort_receipt_digests,
    evaluate_admitted_cohort_claim,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai_service_contracts.baseline_cohort import (
    MINIMUM_COHORT_SAMPLE_SIZE,
    BaselineTreatmentCohortReceipt,
    CohortArm,
    CohortArtifactOrigin,
    CohortClaimRejectionReason,
    CohortClaimRequirement,
    baseline_treatment_cohort_receipt_digest,
)
from fdai_service_contracts.decision_evidence import (
    DecisionCriticalEvidenceReceipt,
    EvidenceConflictStatus,
    decision_critical_evidence_receipt_digest,
)

SCENARIO_SET_DIGEST = "sha256:" + "1" * 64
BASELINE_REPORT_DIGEST = "sha256:" + "2" * 64
BASELINE_PROVENANCE_DIGEST = "sha256:" + "3" * 64
TREATMENT_REPORT_DIGEST = "sha256:" + "4" * 64
TREATMENT_PROVENANCE_DIGEST = "sha256:" + "5" * 64
STATIC_DIGEST = "sha256:" + "6" * 64
BUNDLE_DIGEST = "sha256:" + "7" * 64
REVISION = "git:0123456789abcdef0123456789abcdef01234567"
PURPOSE = "sre-claim-cohort"
NOW = datetime(2026, 9, 1, tzinfo=UTC)
FRESHNESS_SECONDS = 86_400


def _evidence_receipt(
    report_digest: str, provenance_digest: str
) -> DecisionCriticalEvidenceReceipt:
    values: dict[str, Any] = {
        "schema_version": "1.0.0",
        "authority_class": "deployment_observation",
        "source_identity": "principal:sre-cohort-runner",
        "authentication_evidence_digest": STATIC_DIGEST,
        "scope_digest": SCENARIO_SET_DIGEST,
        "purpose_id": PURPOSE,
        "producer_id": "cohort-runner",
        "producer_version": "1.0.0",
        "method_id": "frozen-scenario-replay",
        "method_version": "1.0.0",
        "source_revision": REVISION,
        "evidence_digest": report_digest,
        "provenance_digest": provenance_digest,
        "event_at": NOW - timedelta(hours=2),
        "evidence_cutoff": NOW - timedelta(hours=1),
        "recorded_at": NOW - timedelta(minutes=30),
        "fresh_until": NOW - timedelta(hours=1) + timedelta(seconds=FRESHNESS_SECONDS),
        "freshness_policy_id": "cohort-daily",
        "freshness_policy_version": "1.0.0",
        "freshness_policy_digest": STATIC_DIGEST,
        "freshness_ceiling_seconds": FRESHNESS_SECONDS,
        "completeness_basis_points": 10_000,
        "completeness_evidence_digest": STATIC_DIGEST,
        "conflict_status": EvidenceConflictStatus.CLEAR,
        "conflict_evidence_digest": STATIC_DIGEST,
        "conflict_evidence_digests": (),
        "synthetic": False,
        "execution_authority": False,
    }
    values["receipt_digest"] = decision_critical_evidence_receipt_digest(**values)
    return DecisionCriticalEvidenceReceipt.model_validate(values)


def _arm(arm: CohortArm, report_digest: str, provenance_digest: str) -> dict[str, Any]:
    return {
        "arm": arm,
        "scenario_set_version": "v2026.07",
        "scenario_set_digest": SCENARIO_SET_DIGEST,
        "fdai_revision": REVISION,
        "report_digest": report_digest,
        "provenance_digest": provenance_digest,
        "sample_count": MINIMUM_COHORT_SAMPLE_SIZE,
        "synthetic": False,
        "metrics_complete": True,
        "provenance_complete": True,
        "metrics": (
            {
                "metric_id": "auto_resolution_rate",
                "absolute_value": 0.4,
                "sample_size": MINIMUM_COHORT_SAMPLE_SIZE,
                "lower_bound": 0.25,
                "upper_bound": 0.57,
            },
        ),
        "guards": (
            {
                "guard_id": "policy_violation_escape_rate",
                "observed_basis_points": 0,
                "sample_size": MINIMUM_COHORT_SAMPLE_SIZE,
                "breached": False,
            },
        ),
        "evidence_receipt": _evidence_receipt(report_digest, provenance_digest),
    }


@pytest.fixture
def receipt() -> BaselineTreatmentCohortReceipt:
    values: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cohort_id": "sre-v2026.07-cohort",
        "scenario_set_version": "v2026.07",
        "scenario_set_digest": SCENARIO_SET_DIGEST,
        "fdai_revision": REVISION,
        "artifact_origin": CohortArtifactOrigin.GOVERNED_EXTERNAL,
        "baseline": _arm(
            CohortArm.BASELINE,
            BASELINE_REPORT_DIGEST,
            BASELINE_PROVENANCE_DIGEST,
        ),
        "treatment": _arm(
            CohortArm.TREATMENT,
            TREATMENT_REPORT_DIGEST,
            TREATMENT_PROVENANCE_DIGEST,
        ),
        "evidence_cutoff": NOW - timedelta(hours=1),
        "execution_authority": False,
    }
    values["receipt_digest"] = baseline_treatment_cohort_receipt_digest(**values)
    return BaselineTreatmentCohortReceipt.model_validate(values)


def _requirement() -> CohortClaimRequirement:
    evidence = {
        "allowed_authority_classes": ("deployment_observation",),
        "allowed_source_identities": ("principal:sre-cohort-runner",),
        "scope_digest": SCENARIO_SET_DIGEST,
        "purpose_id": PURPOSE,
        "producer_id": "cohort-runner",
        "producer_version": "1.0.0",
        "method_id": "frozen-scenario-replay",
        "method_version": "1.0.0",
        "source_revision": REVISION,
        "freshness_policy_digest": STATIC_DIGEST,
        "freshness_ceiling_seconds": FRESHNESS_SECONDS,
    }
    return CohortClaimRequirement.model_validate(
        {
            "scenario_set_version": "v2026.07",
            "scenario_set_digest": SCENARIO_SET_DIGEST,
            "fdai_revision": REVISION,
            "required_metric_ids": ("auto_resolution_rate",),
            "required_guard_ids": ("policy_violation_escape_rate",),
            "baseline_evidence": evidence,
            "treatment_evidence": evidence,
        }
    )


def _admission(
    arm_receipt: DecisionCriticalEvidenceReceipt,
    *,
    evidence_digest: str | None = None,
    valid_until: datetime | None = None,
) -> DecisionEvidenceAdmission:
    return DecisionEvidenceAdmission(
        receipt_digest=arm_receipt.receipt_digest,
        verification_bundle_digest=BUNDLE_DIGEST,
        evidence_digest=evidence_digest or arm_receipt.evidence_digest,
        scope_digest=SCENARIO_SET_DIGEST,
        purpose_id=PURPOSE,
        source_revision=REVISION,
        verified_at=NOW - timedelta(minutes=10),
        valid_until=valid_until or NOW + timedelta(hours=1),
    )


def test_current_admissions_make_the_cohort_claim_eligible(
    receipt: BaselineTreatmentCohortReceipt,
) -> None:
    admissions = (
        _admission(receipt.baseline.evidence_receipt),
        _admission(receipt.treatment.evidence_receipt),
    )

    assessment = evaluate_admitted_cohort_claim(
        receipt,
        _requirement(),
        admissions=admissions,
        evaluated_at=NOW,
    )

    assert assessment.claim_eligible is True
    assert assessment.execution_authority is False


def test_one_missing_admission_leaves_the_claim_ineligible(
    receipt: BaselineTreatmentCohortReceipt,
) -> None:
    assessment = evaluate_admitted_cohort_claim(
        receipt,
        _requirement(),
        admissions=(_admission(receipt.baseline.evidence_receipt),),
        evaluated_at=NOW,
    )

    assert assessment.claim_eligible is False
    assert CohortClaimRejectionReason.EVIDENCE_NOT_ADMITTED in assessment.rejection_reasons
    treatment = next(arm for arm in assessment.arms if arm.arm is CohortArm.TREATMENT)
    assert CohortClaimRejectionReason.EVIDENCE_NOT_ADMITTED in treatment.rejection_reasons


def test_an_expired_admission_does_not_count(receipt: BaselineTreatmentCohortReceipt) -> None:
    admissions = (
        _admission(receipt.baseline.evidence_receipt, valid_until=NOW - timedelta(minutes=1)),
        _admission(receipt.treatment.evidence_receipt),
    )

    assert admitted_cohort_receipt_digests(receipt, admissions, evaluated_at=NOW) == frozenset(
        {receipt.treatment.evidence_receipt.receipt_digest}
    )


def test_an_admission_for_another_report_does_not_count(
    receipt: BaselineTreatmentCohortReceipt,
) -> None:
    admissions = (
        _admission(receipt.baseline.evidence_receipt, evidence_digest="sha256:" + "c" * 64),
        _admission(receipt.treatment.evidence_receipt),
    )

    assert admitted_cohort_receipt_digests(receipt, admissions, evaluated_at=NOW) == frozenset(
        {receipt.treatment.evidence_receipt.receipt_digest}
    )


def test_a_missing_receipt_fails_closed_without_admissions() -> None:
    assessment = evaluate_admitted_cohort_claim(None, _requirement(), evaluated_at=NOW)

    assert assessment.claim_eligible is False
    assert assessment.rejection_reasons == (CohortClaimRejectionReason.RECEIPT_MISSING,)


def test_a_naive_evaluation_time_is_rejected(receipt: BaselineTreatmentCohortReceipt) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        admitted_cohort_receipt_digests(receipt, (), evaluated_at=datetime(2026, 9, 1))  # noqa: DTZ001
