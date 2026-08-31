"""Admission-bound eligibility for one retained baseline and treatment cohort."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from fdai_service_contracts.baseline_cohort import (
    BaselineTreatmentCohortReceipt,
    CohortArmReport,
    CohortClaimAssessment,
    CohortClaimRequirement,
    evaluate_cohort_claim,
)

from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    assess_decision_evidence_admission,
)


def admitted_cohort_receipt_digests(
    receipt: BaselineTreatmentCohortReceipt,
    admissions: Iterable[DecisionEvidenceAdmission],
    *,
    evaluated_at: datetime,
) -> frozenset[str]:
    """Return the receipt digests an independent admission currently covers."""

    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("cohort admission evaluation time MUST be timezone-aware")
    normalized_at = evaluated_at.astimezone(UTC)
    arms: dict[str, CohortArmReport] = {
        receipt.baseline.evidence_receipt.receipt_digest: receipt.baseline,
        receipt.treatment.evidence_receipt.receipt_digest: receipt.treatment,
    }
    admitted: set[str] = set()
    for admission in admissions:
        arm = arms.get(admission.receipt_digest)
        if arm is None:
            continue
        rejections = assess_decision_evidence_admission(
            admission,
            expected_evidence_digest=arm.report_digest,
            expected_scope_digest=arm.scenario_set_digest,
            expected_purpose_id=arm.evidence_receipt.purpose_id,
            expected_source_revision=arm.fdai_revision,
            evaluated_at=normalized_at,
        )
        if not rejections:
            admitted.add(admission.receipt_digest)
    return frozenset(admitted)


def evaluate_admitted_cohort_claim(
    receipt: BaselineTreatmentCohortReceipt | None,
    requirement: CohortClaimRequirement,
    *,
    admissions: Iterable[DecisionEvidenceAdmission] = (),
    evaluated_at: datetime,
) -> CohortClaimAssessment:
    """Evaluate cohort eligibility only against currently admitted evidence."""

    if receipt is None:
        return evaluate_cohort_claim(None, requirement, evaluated_at=evaluated_at)
    admitted = admitted_cohort_receipt_digests(
        receipt,
        admissions,
        evaluated_at=evaluated_at,
    )
    return evaluate_cohort_claim(
        receipt,
        requirement,
        evaluated_at=evaluated_at,
        admitted_receipt_digests=admitted,
    )


__all__ = [
    "admitted_cohort_receipt_digests",
    "evaluate_admitted_cohort_claim",
]
