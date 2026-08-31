"""Governed baseline and treatment cohort accounting for claim eligibility.

A retained cohort artifact states facts only. Every trust input - the
evaluated requirement, the import origin, the per-arm admissions, and the
cohort-level admission over the complete receipt digest - is an evaluator
parameter supplied by a trusted caller, so no artifact can describe its own
eligibility.
"""

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
    assess_live_evidence_claim,
)
from fdai_service_contracts.executor_models import ContractBase, Digest, SemVer
from fdai_service_contracts.ontology_query import content_digest

MetricId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]{0,63}$")]
GuardId = MetricId
ScenarioSetVersion = Annotated[str, Field(min_length=8, max_length=32, pattern=r"^v\d{4}\.\d{2}$")]
#: A cohort revision MUST be the same immutable full commit digest operational
#: promotion already requires, so a movable branch or tag name such as ``main``
#: can never identify the code a published claim was measured on.
CommitRevision = Annotated[
    str,
    Field(min_length=40, max_length=64, pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"),
]
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
    """How a cohort artifact reached the evaluator, as told by its importer.

    This is import context, never artifact content. It is supplied by the
    trusted importer channel or caller as an evaluator parameter and is
    deliberately absent from :class:`BaselineTreatmentCohortReceipt`, so no
    artifact can label itself governed.
    """

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


class _CohortArmFacts(ContractBase):
    """Every evaluated fact of one arm, without its evidence receipt."""

    arm: CohortArm
    scenario_set_version: ScenarioSetVersion
    scenario_set_digest: Digest
    fdai_revision: CommitRevision
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

    @model_validator(mode="after")
    def _validate_arm(self) -> _CohortArmFacts:
        metric_ids = tuple(metric.metric_id for metric in self.metrics)
        guard_ids = tuple(guard.guard_id for guard in self.guards)
        for label, values in (("metric", metric_ids), ("guard", guard_ids)):
            if values != tuple(sorted(values)) or len(values) != len(set(values)):
                raise ValueError(f"cohort {label} identifiers MUST be unique and ordered")
        return self


class CohortArmReport(_CohortArmFacts):
    """One arm's retained report, bound to its decision-critical evidence receipt."""

    evidence_receipt: DecisionCriticalEvidenceReceipt


def cohort_arm_fact_digest(report: CohortArmReport) -> str:
    """Return the canonical digest of every fact the evaluator reads for one arm.

    The digest covers the arm identity, its frozen scenario set and digest, its
    pinned revision, its retained sample count, every absolute metric with its
    confidence interval, every zero-threshold guard outcome, the metric and
    provenance completeness flags, the synthetic status, and the report and
    provenance digests. An admission is only accepted for an arm when it was
    issued against exactly this digest, so an admission cannot be replayed onto
    a differently valued arm.
    """

    return content_digest(report.model_dump(mode="json", exclude={"evidence_receipt"}))


def cohort_arm_fact_digest_values(**values: object) -> str:
    """Return the canonical arm fact digest for an arm still being assembled.

    A governed producer needs this digest before it can mint the arm's evidence
    receipt, because the receipt's ``evidence_digest`` MUST be exactly it.
    """

    body = dict(values)
    body.pop("evidence_receipt", None)
    candidate = _CohortArmFacts.model_validate(body)
    return content_digest(candidate.model_dump(mode="json"))


class _BaselineTreatmentCohortReceiptBody(ContractBase):
    schema_version: Literal["1.0.0"] = "1.0.0"
    cohort_id: EvidenceId
    scenario_set_version: ScenarioSetVersion
    scenario_set_digest: Digest
    fdai_revision: CommitRevision
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
    """Retain both cohort arms without asserting that the claim is eligible.

    The receipt carries no origin, admission, requirement, or verdict. Its
    ``receipt_digest`` covers every retained cohort fact, so a trusted
    cohort-level admission issued against that one digest cannot be replayed
    onto a relabelled or rehashed artifact.
    """

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
    """Governed expectation a cohort artifact is evaluated against.

    This contract is never deserialized from a cohort artifact. It is built
    only from the trusted versioned repository policy plus an expected revision
    supplied by the trusted caller, so an evidence bundle cannot weaken the
    metrics, guards, frozen set, or minimum sample size it is measured against.
    """

    policy_id: EvidenceId
    policy_version: SemVer
    scenario_set_version: ScenarioSetVersion
    scenario_set_digest: Digest
    fdai_revision: CommitRevision
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
        if self.baseline_evidence.purpose_id != self.treatment_evidence.purpose_id:
            raise ValueError("both cohort evidence requirements MUST pin one claim purpose")
        return self

    @property
    def claim_purpose_id(self) -> str:
        """Return the one trusted purpose a cohort-level admission MUST carry."""

        return self.baseline_evidence.purpose_id


class CohortClaimRejectionReason(StrEnum):
    """Why a retained cohort cannot support a published claim."""

    ARM_FACT_MISMATCH = "arm_fact_mismatch"
    ARMS_NOT_DISTINCT = "arms_not_distinct"
    ARTIFACT_UNGOVERNED = "artifact_ungoverned"
    COHORT_NOT_ADMITTED = "cohort_not_admitted"
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
    """Deterministic eligibility result for one governed cohort artifact.

    ``artifact_origin`` is an evaluation output that echoes the trusted import
    context back to the reader. It is never read from an artifact.
    """

    evaluated_at: datetime
    claim_eligible: bool
    rejection_reasons: tuple[CohortClaimRejectionReason, ...]
    arms: tuple[CohortArmAssessment, ...] = ()
    receipt_digest: Digest | None = None
    artifact_origin: CohortArtifactOrigin = CohortArtifactOrigin.REPOSITORY
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
        if (
            self.claim_eligible
            and self.artifact_origin is not CohortArtifactOrigin.GOVERNED_EXTERNAL
        ):
            raise ValueError("an eligible cohort claim MUST cite a governed external artifact")
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
    if report.evidence_receipt.evidence_digest != cohort_arm_fact_digest(report):
        reasons.add(CohortClaimRejectionReason.ARM_FACT_MISMATCH)
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
        artifact_origin=CohortArtifactOrigin.REPOSITORY,
    )


def _arms_share_evidence(receipt: BaselineTreatmentCohortReceipt) -> bool:
    """Return whether the two arms reuse one report, provenance, or receipt."""

    baseline, treatment = receipt.baseline, receipt.treatment
    return (
        baseline.report_digest == treatment.report_digest
        or baseline.provenance_digest == treatment.provenance_digest
        or baseline.evidence_receipt.receipt_digest == treatment.evidence_receipt.receipt_digest
        or baseline.evidence_receipt.evidence_digest == treatment.evidence_receipt.evidence_digest
    )


def evaluate_cohort_claim(
    receipt: BaselineTreatmentCohortReceipt | None,
    requirement: CohortClaimRequirement,
    *,
    evaluated_at: datetime,
    admitted_receipt_digests: frozenset[str] = frozenset(),
    import_origin: CohortArtifactOrigin = CohortArtifactOrigin.REPOSITORY,
    admitted_cohort_receipt_digest: str | None = None,
) -> CohortClaimAssessment:
    """Return eligible only for a governed, complete, non-synthetic, admitted cohort.

    Every trust input is a parameter, never artifact content. ``requirement``
    MUST come from the trusted repository policy, ``import_origin`` from the
    trusted importer channel or caller, and both ``admitted_receipt_digests``
    and ``admitted_cohort_receipt_digest`` from a trusted admission source. A
    caller that passes none - which is what the repository importer does on its
    own - never reaches an eligible verdict.

    ``admitted_cohort_receipt_digest`` is the cohort-level admission that binds
    the complete retained receipt, in addition to the per-arm admissions. It
    MUST equal ``receipt.receipt_digest``, so relabelling or rehashing any part
    of the artifact leaves the claim ineligible.
    """

    normalized_at = CohortClaimAssessment._normalize_evaluated_at(evaluated_at)
    if receipt is None:
        return missing_cohort_claim(evaluated_at=normalized_at)

    reasons: set[CohortClaimRejectionReason] = set()
    if import_origin is not CohortArtifactOrigin.GOVERNED_EXTERNAL:
        reasons.add(CohortClaimRejectionReason.ARTIFACT_UNGOVERNED)
    if (
        admitted_cohort_receipt_digest is None
        or admitted_cohort_receipt_digest != receipt.receipt_digest
    ):
        reasons.add(CohortClaimRejectionReason.COHORT_NOT_ADMITTED)
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
    if _arms_share_evidence(receipt):
        reasons.add(CohortClaimRejectionReason.ARMS_NOT_DISTINCT)

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
        artifact_origin=import_origin,
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
    "cohort_arm_fact_digest",
    "cohort_arm_fact_digest_values",
    "evaluate_cohort_claim",
    "missing_cohort_claim",
]
