"""Admission-bound eligibility for one retained baseline and treatment cohort.

Eligibility needs an admission per arm, and an admission is only ever obtained
from a trusted source: an injected shared decision-evidence admission provider,
or a separately supplied complete proof bundle read back through the existing
decision-evidence verifier registry. A cohort artifact never carries its own
admissions, so an artifact can never admit itself.

Every admission is rechecked against the canonical digest of every evaluated
arm fact, so an admission issued for one arm's values cannot be replayed onto
an arm whose metrics, guards, sample count, or provenance differ.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from fdai_service_contracts.baseline_cohort import (
    BaselineTreatmentCohortReceipt,
    CohortArmReport,
    CohortClaimAssessment,
    CohortClaimRequirement,
    cohort_arm_fact_digest,
    evaluate_cohort_claim,
)
from fdai_service_contracts.decision_evidence import LiveEvidenceClaimRequirement

from fdai.core.readiness.decision_evidence import DecisionEvidenceReadinessGate
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    DecisionEvidenceAdmissionProvider,
    assess_decision_evidence_admission,
)


def cohort_arm_reports(
    receipt: BaselineTreatmentCohortReceipt,
) -> tuple[CohortArmReport, CohortArmReport]:
    """Return both retained arms in a fixed baseline-then-treatment order."""

    return receipt.baseline, receipt.treatment


def admitted_cohort_receipt_digests(
    receipt: BaselineTreatmentCohortReceipt,
    admissions: Iterable[DecisionEvidenceAdmission],
    *,
    evaluated_at: datetime,
) -> frozenset[str]:
    """Return the receipt digests a trusted current admission actually covers."""

    normalized_at = _aware_utc(evaluated_at)
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
            expected_evidence_digest=cohort_arm_fact_digest(arm),
            expected_scope_digest=arm.scenario_set_digest,
            expected_purpose_id=arm.evidence_receipt.purpose_id,
            expected_source_revision=arm.fdai_revision,
            evaluated_at=normalized_at,
        )
        if not rejections:
            admitted.add(admission.receipt_digest)
    return frozenset(admitted)


async def provider_cohort_admissions(
    receipt: BaselineTreatmentCohortReceipt,
    *,
    provider: DecisionEvidenceAdmissionProvider | None,
) -> tuple[DecisionEvidenceAdmission, ...]:
    """Ask one injected trusted shared admission provider about each arm."""

    if provider is None:
        return ()
    admissions: list[DecisionEvidenceAdmission] = []
    for arm in cohort_arm_reports(receipt):
        admission = await provider.admit(
            evidence_digest=cohort_arm_fact_digest(arm),
            scope_digest=arm.scenario_set_digest,
            purpose_id=arm.evidence_receipt.purpose_id,
            source_revision=arm.fdai_revision,
        )
        if admission is not None:
            admissions.append(admission)
    return tuple(admissions)


async def verified_cohort_admissions(
    receipt: BaselineTreatmentCohortReceipt,
    requirement: CohortClaimRequirement,
    *,
    gate: DecisionEvidenceReadinessGate,
    evaluated_at: datetime,
) -> tuple[DecisionEvidenceAdmission, ...]:
    """Read each arm back through the existing verifier registry for a proof bundle.

    The gate resolves a reviewed verifier binding, requires five independent
    proofs over the separately supplied bundle, and only then emits an
    admission. The cohort artifact supplies the receipt, never the proof.
    """

    normalized_at = _aware_utc(evaluated_at)
    pairs: tuple[tuple[CohortArmReport, LiveEvidenceClaimRequirement], ...] = (
        (receipt.baseline, requirement.baseline_evidence),
        (receipt.treatment, requirement.treatment_evidence),
    )
    admissions: list[DecisionEvidenceAdmission] = []
    for arm, evidence_requirement in pairs:
        result = await gate.evaluate(
            arm.evidence_receipt,
            evidence_requirement,
            evaluated_at=normalized_at,
        )
        if result.admission is not None:
            admissions.append(result.admission)
    return tuple(admissions)


def evaluate_admitted_cohort_claim(
    receipt: BaselineTreatmentCohortReceipt | None,
    requirement: CohortClaimRequirement,
    *,
    admissions: Iterable[DecisionEvidenceAdmission] = (),
    evaluated_at: datetime,
) -> CohortClaimAssessment:
    """Evaluate cohort eligibility only against currently admitted evidence.

    ``admissions`` MUST originate from :func:`provider_cohort_admissions` or
    :func:`verified_cohort_admissions`. Passing none - the state of any caller
    that only read a repository artifact - keeps the claim ineligible.
    """

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


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("cohort admission evaluation time MUST be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "admitted_cohort_receipt_digests",
    "cohort_arm_reports",
    "evaluate_admitted_cohort_claim",
    "provider_cohort_admissions",
    "verified_cohort_admissions",
]
