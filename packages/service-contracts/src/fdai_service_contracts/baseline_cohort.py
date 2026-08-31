"""Governed baseline and treatment cohort accounting for claim eligibility."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from fdai_service_contracts.decision_evidence import (
    DecisionCriticalEvidenceReceipt,
    EvidenceId,
    LiveEvidenceClaimAssessment,
    LiveEvidenceClaimRequirement,
    SourceIdentity,
    assess_live_evidence_claim,
)
from fdai_service_contracts.executor_models import ContractBase, Digest
from fdai_service_contracts.ontology_query import content_digest

MetricId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]{0,63}$")]
GuardId = MetricId
ScenarioSetVersion = Annotated[str, Field(min_length=8, max_length=32, pattern=r"^v\d{4}\.\d{2}$")]
BasisPoints = Annotated[int, Field(strict=True, ge=0, le=10_000)]
SampleCount = Annotated[int, Field(strict=True, ge=0, le=1_000_000)]

#: A published cohort claim is never eligible below this retained sample size.
MINIMUM_COHORT_SAMPLE_SIZE = 30
_MAX_MEASURES = 32


class CohortArm(StrEnum):
    """The two arms one claim compares on a single frozen set and revision."""

    BASELINE = "baseline"
    TREATMENT = "treatment"


class CohortArtifactOrigin(StrEnum):
    """Where a cohort artifact came from, which never grants authority itself."""

    REPOSITORY = "repository"
    GOVERNED_EXTERNAL = "governed_external"


class CohortMetricEstimate(ContractBase):
    """One absolute metric value with the interval of the retained cohort."""

    metric_id: MetricId
    absolute_value: float = Field(ge=0.0)
    sample_size: SampleCount
    confidence_level_basis_points: Annotated[int, Field(strict=True, ge=5_000, le=9_999)] = 9_500
    lower_bound: float = Field(ge=0.0)
    upper_bound: float = Field(ge=0.0)

    @model_validator(mode="after")
    def _validate_interval(self) -> CohortMetricEstimate:
        if not self.lower_bound <= self.absolute_value <= self.upper_bound:
            raise ValueError("cohort metric interval MUST contain its absolute value")
        return self


class CohortGuardOutcome(ContractBase):
    """One zero-threshold guard outcome observed over the retained cohort."""

    guard_id: GuardId
    observed_basis_points: BasisPoints
    maximum_basis_points: Literal[0] = 0
    sample_size: SampleCount
    breached: bool

    @model_validator(mode="after")
    def _validate_breach(self) -> CohortGuardOutcome:
        if self.breached != (self.observed_basis_points > self.maximum_basis_points):
            raise ValueError("cohort guard breach does not match its observed value")
        return self


class CohortArmReport(ContractBase):
    """One arm's retained report, bound to its decision-critical evidence receipt."""

    arm: CohortArm
    scenario_set_version: ScenarioSetVersion
    scenario_set_digest: Digest
    fdai_revision: SourceIdentity
    report_digest: Digest
    provenance_digest: Digest
    sample_count: SampleCount
    synthetic: bool
    metrics_complete: bool
    provenance_complete: bool
    metrics: Annotated[
        tuple[CohortMetricEstimate, ...],
        Field(min_length=1, max_length=_MAX_MEASURES),
    ]
    guards: Annotated[
        tuple[CohortGuardOutcome, ...],
        Field(min_length=1, max_length=_MAX_MEASURES),
    ]
    evidence_receipt: DecisionCriticalEvidenceReceipt

    @model_validator(mode="after")
    def _validate_arm(self) -> CohortArmReport:
        metric_ids = tuple(metric.metric_id for metric in self.metrics)
        guard_ids = tuple(guard.guard_id for guard in self.guards)
        for label, values in (("metric", metric_ids), ("guard", guard_ids)):
            if values != tuple(sorted(values)) or len(values) != len(set(values)):
                raise ValueError(f"cohort {label} identifiers MUST be unique and ordered")
        return self


class _BaselineTreatmentCohortReceiptBody(ContractBase):
    schema_version: Literal["1.0.0"] = "1.0.0"
    cohort_id: EvidenceId
    scenario_set_version: ScenarioSetVersion
    scenario_set_digest: Digest
    fdai_revision: SourceIdentity
    artifact_origin: CohortArtifactOrigin
    baseline: CohortArmReport
    treatment: CohortArmReport
    evidence_cutoff: datetime
    execution_authority: Literal[False] = False

    @field_validator("evidence_cutoff")
    @classmethod
    def _normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cohort evidence cutoff MUST include a timezone")
        return value.astimezone(UTC)


class BaselineTreatmentCohortReceipt(_BaselineTreatmentCohortReceiptBody):
    """Retain both cohort arms without asserting that the claim is eligible."""

    receipt_digest: Digest

    @model_validator(mode="after")
    def _validate_receipt(self) -> BaselineTreatmentCohortReceipt:
        if self.baseline.arm is not CohortArm.BASELINE:
            raise ValueError("cohort baseline arm MUST be labelled baseline")
        if self.treatment.arm is not CohortArm.TREATMENT:
            raise ValueError("cohort treatment arm MUST be labelled treatment")
        expected = content_digest(self.model_dump(mode="json", exclude={"receipt_digest"}))
        if self.receipt_digest != expected:
            raise ValueError("cohort receipt digest does not match its content")
        return self


class CohortClaimRequirement(ContractBase):
    """Governed expectation a cohort artifact is evaluated against."""

    scenario_set_version: ScenarioSetVersion
    scenario_set_digest: Digest
    fdai_revision: SourceIdentity
    minimum_sample_size: Annotated[
        int,
        Field(strict=True, ge=MINIMUM_COHORT_SAMPLE_SIZE, le=1_000_000),
    ] = MINIMUM_COHORT_SAMPLE_SIZE
    required_metric_ids: Annotated[
        tuple[MetricId, ...],
        Field(min_length=1, max_length=_MAX_MEASURES),
    ]
    required_guard_ids: Annotated[
        tuple[GuardId, ...],
        Field(min_length=1, max_length=_MAX_MEASURES),
    ]
    baseline_evidence: LiveEvidenceClaimRequirement
    treatment_evidence: LiveEvidenceClaimRequirement

    @model_validator(mode="after")
    def _validate_requirement(self) -> CohortClaimRequirement:
        for label, values in (
            ("metric", self.required_metric_ids),
            ("guard", self.required_guard_ids),
        ):
            if values != tuple(sorted(values)) or len(values) != len(set(values)):
                raise ValueError(f"required cohort {label} identifiers MUST be unique and ordered")
        for label, evidence in (
            ("baseline", self.baseline_evidence),
            ("treatment", self.treatment_evidence),
        ):
            if evidence.source_revision != self.fdai_revision:
                raise ValueError(f"{label} evidence requirement MUST pin the cohort revision")
            if evidence.scope_digest != self.scenario_set_digest:
                raise ValueError(f"{label} evidence requirement MUST pin the frozen scenario set")
        return self


class CohortClaimRejectionReason(StrEnum):
    """Why a retained cohort cannot support a published claim."""

    ARTIFACT_UNGOVERNED = "artifact_ungoverned"
    CONFIDENCE_INTERVAL_INCOMPLETE = "confidence_interval_incomplete"
    COHORT_UNDERSIZED = "cohort_undersized"
    EVIDENCE_NOT_ADMITTED = "evidence_not_admitted"
    EVIDENCE_PREFLIGHT_REJECTED = "evidence_preflight_rejected"
    GUARD_BREACHED = "guard_breached"
    GUARD_INCOMPLETE = "guard_incomplete"
    METRICS_INCOMPLETE = "metrics_incomplete"
    PROVENANCE_INCOMPLETE = "provenance_incomplete"
    RECEIPT_MISSING = "receipt_missing"
    REPORT_DIGEST_MISMATCH = "report_digest_mismatch"
    REVISION_MISMATCH = "revision_mismatch"
    SCENARIO_SET_MISMATCH = "scenario_set_mismatch"
    SYNTHETIC = "synthetic"


class CohortArmAssessment(ContractBase):
    """Per-arm rejection detail that never grants authority."""

    arm: CohortArm
    rejection_reasons: tuple[CohortClaimRejectionReason, ...]
    evidence_preflight: LiveEvidenceClaimAssessment | None = None

    @model_validator(mode="after")
    def _validate_reasons(self) -> CohortArmAssessment:
        if self.rejection_reasons != tuple(sorted(set(self.rejection_reasons), key=str)):
            raise ValueError("cohort arm rejection reasons MUST be unique and ordered")
        return self


class CohortClaimAssessment(ContractBase):
    """Deterministic eligibility result for one governed cohort artifact."""

    evaluated_at: datetime
    claim_eligible: bool
    rejection_reasons: tuple[CohortClaimRejectionReason, ...]
    arms: tuple[CohortArmAssessment, ...] = ()
    receipt_digest: Digest | None = None
    execution_authority: Literal[False] = False

    @field_validator("evaluated_at")
    @classmethod
    def _normalize_evaluated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cohort claim evaluation time MUST include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _validate_assessment(self) -> CohortClaimAssessment:
        if self.rejection_reasons != tuple(sorted(set(self.rejection_reasons), key=str)):
            raise ValueError("cohort claim rejection reasons MUST be unique and ordered")
        if self.claim_eligible == bool(self.rejection_reasons):
            raise ValueError("cohort claim eligibility does not match its reasons")
        arm_reasons = {reason for arm in self.arms for reason in arm.rejection_reasons}
        if not arm_reasons <= set(self.rejection_reasons):
            raise ValueError("cohort claim reasons MUST include every arm reason")
        if self.claim_eligible and self.receipt_digest is None:
            raise ValueError("an eligible cohort claim MUST cite its receipt digest")
        return self


def baseline_treatment_cohort_receipt_digest(**values: object) -> str:
    """Return the canonical digest for a baseline and treatment cohort body."""

    body = dict(values)
    body.pop("receipt_digest", None)
    candidate = _BaselineTreatmentCohortReceiptBody.model_validate(body)
    return content_digest(candidate.model_dump(mode="json"))


def _assess_arm(
    report: CohortArmReport,
    requirement: CohortClaimRequirement,
    evidence_requirement: LiveEvidenceClaimRequirement,
    *,
    evaluated_at: datetime,
    admitted_receipt_digests: frozenset[str],
) -> CohortArmAssessment:
    reasons: set[CohortClaimRejectionReason] = set()
    if report.synthetic or report.evidence_receipt.synthetic:
        reasons.add(CohortClaimRejectionReason.SYNTHETIC)
    if report.scenario_set_version != requirement.scenario_set_version or (
        report.scenario_set_digest != requirement.scenario_set_digest
    ):
        reasons.add(CohortClaimRejectionReason.SCENARIO_SET_MISMATCH)
    if report.fdai_revision != requirement.fdai_revision:
        reasons.add(CohortClaimRejectionReason.REVISION_MISMATCH)
    if report.evidence_receipt.source_revision != report.fdai_revision:
        reasons.add(CohortClaimRejectionReason.REVISION_MISMATCH)
    if report.evidence_receipt.scope_digest != report.scenario_set_digest:
        reasons.add(CohortClaimRejectionReason.SCENARIO_SET_MISMATCH)
    if report.evidence_receipt.evidence_digest != report.report_digest:
        reasons.add(CohortClaimRejectionReason.REPORT_DIGEST_MISMATCH)
    if report.evidence_receipt.provenance_digest != report.provenance_digest:
        reasons.add(CohortClaimRejectionReason.REPORT_DIGEST_MISMATCH)
    if report.sample_count < requirement.minimum_sample_size:
        reasons.add(CohortClaimRejectionReason.COHORT_UNDERSIZED)
    if not report.metrics_complete:
        reasons.add(CohortClaimRejectionReason.METRICS_INCOMPLETE)
    if not report.provenance_complete:
        reasons.add(CohortClaimRejectionReason.PROVENANCE_INCOMPLETE)

    metric_ids = {metric.metric_id for metric in report.metrics}
    if not set(requirement.required_metric_ids) <= metric_ids:
        reasons.add(CohortClaimRejectionReason.METRICS_INCOMPLETE)
    if any(metric.sample_size != report.sample_count for metric in report.metrics):
        reasons.add(CohortClaimRejectionReason.CONFIDENCE_INTERVAL_INCOMPLETE)

    guards = {guard.guard_id: guard for guard in report.guards}
    if not set(requirement.required_guard_ids) <= set(guards):
        reasons.add(CohortClaimRejectionReason.GUARD_INCOMPLETE)
    if any(guard.sample_size != report.sample_count for guard in report.guards):
        reasons.add(CohortClaimRejectionReason.GUARD_INCOMPLETE)
    if any(guard.breached for guard in report.guards):
        reasons.add(CohortClaimRejectionReason.GUARD_BREACHED)

    preflight = assess_live_evidence_claim(
        report.evidence_receipt,
        evidence_requirement,
        evaluated_at=evaluated_at,
    )
    if not preflight.eligible_for_verification:
        reasons.add(CohortClaimRejectionReason.EVIDENCE_PREFLIGHT_REJECTED)
    if report.evidence_receipt.receipt_digest not in admitted_receipt_digests:
        reasons.add(CohortClaimRejectionReason.EVIDENCE_NOT_ADMITTED)

    return CohortArmAssessment(
        arm=report.arm,
        rejection_reasons=tuple(sorted(reasons, key=str)),
        evidence_preflight=preflight,
    )


def missing_cohort_claim(*, evaluated_at: datetime) -> CohortClaimAssessment:
    """Return the fail-closed result for an absent cohort receipt."""

    return CohortClaimAssessment(
        evaluated_at=CohortClaimAssessment._normalize_evaluated_at(evaluated_at),
        claim_eligible=False,
        rejection_reasons=(CohortClaimRejectionReason.RECEIPT_MISSING,),
    )


def evaluate_cohort_claim(
    receipt: BaselineTreatmentCohortReceipt | None,
    requirement: CohortClaimRequirement,
    *,
    evaluated_at: datetime,
    admitted_receipt_digests: frozenset[str] = frozenset(),
) -> CohortClaimAssessment:
    """Return eligible only for a governed, complete, non-synthetic, admitted cohort."""

    normalized_at = CohortClaimAssessment._normalize_evaluated_at(evaluated_at)
    if receipt is None:
        return missing_cohort_claim(evaluated_at=normalized_at)

    reasons: set[CohortClaimRejectionReason] = set()
    if receipt.artifact_origin is not CohortArtifactOrigin.GOVERNED_EXTERNAL:
        reasons.add(CohortClaimRejectionReason.ARTIFACT_UNGOVERNED)
    if receipt.scenario_set_version != requirement.scenario_set_version or (
        receipt.scenario_set_digest != requirement.scenario_set_digest
    ):
        reasons.add(CohortClaimRejectionReason.SCENARIO_SET_MISMATCH)
    if receipt.fdai_revision != requirement.fdai_revision:
        reasons.add(CohortClaimRejectionReason.REVISION_MISMATCH)
    if receipt.baseline.scenario_set_version != receipt.treatment.scenario_set_version or (
        receipt.baseline.scenario_set_digest != receipt.treatment.scenario_set_digest
    ):
        reasons.add(CohortClaimRejectionReason.SCENARIO_SET_MISMATCH)
    if receipt.baseline.fdai_revision != receipt.treatment.fdai_revision:
        reasons.add(CohortClaimRejectionReason.REVISION_MISMATCH)

    arms = (
        _assess_arm(
            receipt.baseline,
            requirement,
            requirement.baseline_evidence,
            evaluated_at=normalized_at,
            admitted_receipt_digests=admitted_receipt_digests,
        ),
        _assess_arm(
            receipt.treatment,
            requirement,
            requirement.treatment_evidence,
            evaluated_at=normalized_at,
            admitted_receipt_digests=admitted_receipt_digests,
        ),
    )
    for arm in arms:
        reasons.update(arm.rejection_reasons)
    ordered = tuple(sorted(reasons, key=str))
    return CohortClaimAssessment(
        evaluated_at=normalized_at,
        claim_eligible=not ordered,
        rejection_reasons=ordered,
        arms=arms,
        receipt_digest=receipt.receipt_digest,
    )


__all__ = [
    "MINIMUM_COHORT_SAMPLE_SIZE",
    "BaselineTreatmentCohortReceipt",
    "CohortArm",
    "CohortArmAssessment",
    "CohortArmReport",
    "CohortArtifactOrigin",
    "CohortClaimAssessment",
    "CohortClaimRejectionReason",
    "CohortClaimRequirement",
    "CohortGuardOutcome",
    "CohortMetricEstimate",
    "baseline_treatment_cohort_receipt_digest",
    "evaluate_cohort_claim",
    "missing_cohort_claim",
]
