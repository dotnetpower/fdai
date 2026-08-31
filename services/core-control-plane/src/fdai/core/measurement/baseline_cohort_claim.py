"""Admission-bound eligibility for one retained baseline and treatment cohort.

Eligibility needs an admission per arm plus one cohort-level admission over the
complete receipt digest, and an admission is only ever obtained from a trusted
source: an injected shared decision-evidence admission provider, or a
separately supplied complete proof bundle read back through the existing
decision-evidence verifier registry. A cohort artifact never carries its own
admissions or its own origin, so an artifact can never admit itself.

Every arm admission is rechecked against the canonical digest of every
evaluated arm fact, so an admission issued for one arm's values cannot be
replayed onto an arm whose metrics, guards, sample count, or provenance differ.
The cohort admission is rechecked against the receipt digest that covers both
arms together, so a relabelled or rehashed artifact loses it.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from fdai_service_contracts.baseline_cohort import (
    BaselineTreatmentCohortReceipt,
    CohortArmReport,
    CohortArtifactOrigin,
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


def admitted_cohort_claim_digest(
    receipt: BaselineTreatmentCohortReceipt,
    requirement: CohortClaimRequirement,
    admissions: Iterable[DecisionEvidenceAdmission],
    *,
    evaluated_at: datetime,
) -> str | None:
    """Return the cohort receipt digest a trusted cohort-level admission covers.

    The admission MUST bind the complete retained receipt: its receipt and
    evidence digests are both the cohort ``receipt_digest``, and its scope,
    purpose, and revision are rechecked against the trusted requirement rather
    than against anything the artifact declares. Any relabelled or rehashed
    artifact changes that digest and is left uncovered.
    """

    normalized_at = _aware_utc(evaluated_at)
    for admission in admissions:
        if admission.receipt_digest != receipt.receipt_digest:
            continue
        rejections = assess_decision_evidence_admission(
            admission,
            expected_evidence_digest=receipt.receipt_digest,
            expected_scope_digest=requirement.scenario_set_digest,
            expected_purpose_id=requirement.claim_purpose_id,
            expected_source_revision=requirement.fdai_revision,
            evaluated_at=normalized_at,
        )
        if not rejections:
            return receipt.receipt_digest
    return None


async def provider_cohort_admissions(
    receipt: BaselineTreatmentCohortReceipt,
    requirement: CohortClaimRequirement,
    *,
    provider: DecisionEvidenceAdmissionProvider | None,
) -> tuple[DecisionEvidenceAdmission, ...]:
    """Ask one injected trusted shared admission provider about the cohort and each arm."""

    if provider is None:
        return ()
    admissions: list[DecisionEvidenceAdmission] = []
    cohort_admission = await provider.admit(
        evidence_digest=receipt.receipt_digest,
        scope_digest=requirement.scenario_set_digest,
        purpose_id=requirement.claim_purpose_id,
        source_revision=requirement.fdai_revision,
    )
    if cohort_admission is not None:
        admissions.append(cohort_admission)
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

    The registry verifies arm evidence receipts only, so a governed external
    import still needs its cohort-level admission from the trusted importer
    channel, as :func:`provider_cohort_admissions` obtains it.
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
    import_origin: CohortArtifactOrigin = CohortArtifactOrigin.REPOSITORY,
    evaluated_at: datetime,
) -> CohortClaimAssessment:
    """Evaluate cohort eligibility only against currently admitted evidence.

    ``admissions`` MUST originate from :func:`provider_cohort_admissions` or
    :func:`verified_cohort_admissions`, and ``import_origin`` from the trusted
    importer channel or caller. Passing neither - the state of any caller that
    only read a repository artifact - keeps the claim ineligible.
    """

    if receipt is None:
        return evaluate_cohort_claim(None, requirement, evaluated_at=evaluated_at)
    current = tuple(admissions)
    admitted = admitted_cohort_receipt_digests(
        receipt,
        current,
        evaluated_at=evaluated_at,
    )
    return evaluate_cohort_claim(
        receipt,
        requirement,
        evaluated_at=evaluated_at,
        admitted_receipt_digests=admitted,
        import_origin=import_origin,
        admitted_cohort_receipt_digest=admitted_cohort_claim_digest(
            receipt,
            requirement,
            current,
            evaluated_at=evaluated_at,
        ),
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("cohort admission evaluation time MUST be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "admitted_cohort_claim_digest",
    "admitted_cohort_receipt_digests",
    "cohort_arm_reports",
    "evaluate_admitted_cohort_claim",
    "provider_cohort_admissions",
    "verified_cohort_admissions",
]
