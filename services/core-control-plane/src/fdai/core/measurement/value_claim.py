"""Independent, baseline-relative settlement of one workflow value claim.

A value claim states that a promoted Workflow or ActionType improved one
operational metric (duration, cost, or count) against a retained baseline. The
settlement is a pure, replay-stable reducer: it accepts only independently
observed, complete cohorts that share one scenario set, never an executor report,
and it reports the conservative bound of the 95% interval instead of the point
estimate. The ledger records measured operational units only. Converting units to
business revenue or downtime cost is a deployment decision and is not modeled here.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from fdai_service_contracts.ontology_query import content_digest
from pydantic import Field, field_validator, model_validator

from fdai.shared.contracts.models import ContractBase

NonEmpty = Annotated[str, Field(min_length=1)]
EvidenceRefs = Annotated[tuple[NonEmpty, ...], Field(min_length=1, max_length=32)]

_Z_95 = Decimal("1.96")
_MAX_SAMPLES = 100_000


class ValueUnit(StrEnum):
    DURATION_SECONDS = "duration_seconds"
    COST_AMOUNT = "cost_amount"
    COUNT = "count"


class ValueDirection(StrEnum):
    DECREASE_IS_BETTER = "decrease_is_better"
    INCREASE_IS_BETTER = "increase_is_better"


class CohortRole(StrEnum):
    BASELINE = "baseline"
    TREATMENT = "treatment"


class ObservationLane(StrEnum):
    INDEPENDENT_OBSERVATION = "independent_observation"
    EXECUTOR_REPORT = "executor_report"


class ValueClaimStatus(StrEnum):
    IMPROVED = "improved"
    NO_SIGNIFICANT_CHANGE = "no_significant_change"
    REGRESSED = "regressed"
    BLOCKED_POLICY_ESCAPE = "blocked_policy_escape"
    UNSETTLED_NOT_INDEPENDENT = "unsettled_not_independent"
    UNSETTLED_INCOMPLETE = "unsettled_incomplete"
    UNSETTLED_SCOPE_MISMATCH = "unsettled_scope_mismatch"
    UNSETTLED_INSUFFICIENT_SAMPLE = "unsettled_insufficient_sample"


class ValueClaimDeclaration(ContractBase):
    """What a promoted process claims, fixed before any settlement."""

    claim_id: NonEmpty
    workflow_ref: NonEmpty
    workflow_version: NonEmpty
    objective_ref: NonEmpty
    metric_name: NonEmpty
    unit: ValueUnit
    currency: NonEmpty | None = None
    direction: ValueDirection
    scenario_set_version: NonEmpty
    window_start: datetime
    window_end: datetime
    min_samples_per_cohort: Annotated[int, Field(ge=2, le=_MAX_SAMPLES)]

    @field_validator("window_start", "window_end")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("value claim window timestamps MUST be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_declaration(self) -> ValueClaimDeclaration:
        if self.window_end <= self.window_start:
            raise ValueError("value claim window end MUST follow start")
        if (self.unit is ValueUnit.COST_AMOUNT) != (self.currency is not None):
            raise ValueError("a currency MUST be declared exactly for cost_amount claims")
        return self


class ValueCohortObservation(ContractBase):
    """One retained cohort of per-event measurements for the declared metric."""

    role: CohortRole
    lane: ObservationLane
    scenario_set_version: NonEmpty
    currency: NonEmpty | None = None
    complete: bool
    samples: Annotated[tuple[Decimal, ...], Field(max_length=_MAX_SAMPLES)]
    policy_escape_count: Annotated[int, Field(ge=0)] = 0
    evidence_refs: EvidenceRefs
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cohort observation time MUST be timezone-aware")
        return value

    @field_validator("samples")
    @classmethod
    def require_finite(cls, value: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
        if any(not item.is_finite() for item in value):
            raise ValueError("cohort samples MUST be finite decimals")
        return value


class ValueClaimSettlement(ContractBase):
    """Replay-stable settlement. Only an improved status carries realized value."""

    claim_id: NonEmpty
    status: ValueClaimStatus
    unit: ValueUnit
    currency: NonEmpty | None = None
    baseline_sample_count: int
    treatment_sample_count: int
    mean_improvement_per_event: Decimal | None = None
    conservative_improvement_per_event: Decimal | None = None
    conservative_total_improvement: Decimal | None = None
    reason_codes: tuple[NonEmpty, ...] = ()
    evidence_refs: tuple[NonEmpty, ...] = ()
    settlement_digest: NonEmpty


def settle_value_claim(
    declaration: ValueClaimDeclaration,
    cohorts: tuple[ValueCohortObservation, ...],
) -> ValueClaimSettlement:
    """Settle one claim, or return the first honest reason it cannot be settled."""

    baseline, treatment, shape_reason = _select_cohorts(cohorts)
    if baseline is None or treatment is None:
        return _unsettled(
            declaration,
            ValueClaimStatus.UNSETTLED_INCOMPLETE,
            (shape_reason,),
            baseline,
            treatment,
        )
    if any(
        item.lane is not ObservationLane.INDEPENDENT_OBSERVATION for item in (baseline, treatment)
    ):
        return _unsettled(
            declaration,
            ValueClaimStatus.UNSETTLED_NOT_INDEPENDENT,
            ("executor_report_is_not_evidence",),
            baseline,
            treatment,
        )
    if treatment.policy_escape_count > 0:
        return _unsettled(
            declaration,
            ValueClaimStatus.BLOCKED_POLICY_ESCAPE,
            ("policy_escape_blocks_value",),
            baseline,
            treatment,
        )
    mismatch = _scope_mismatch(declaration, baseline, treatment)
    if mismatch:
        return _unsettled(
            declaration,
            ValueClaimStatus.UNSETTLED_SCOPE_MISMATCH,
            mismatch,
            baseline,
            treatment,
        )
    if not (baseline.complete and treatment.complete):
        return _unsettled(
            declaration,
            ValueClaimStatus.UNSETTLED_INCOMPLETE,
            ("cohort_not_complete",),
            baseline,
            treatment,
        )
    floor = declaration.min_samples_per_cohort
    if len(baseline.samples) < floor or len(treatment.samples) < floor:
        return _unsettled(
            declaration,
            ValueClaimStatus.UNSETTLED_INSUFFICIENT_SAMPLE,
            ("sample_floor_not_met",),
            baseline,
            treatment,
        )

    mean_delta = _mean(treatment.samples) - _mean(baseline.samples)
    margin = (
        _Z_95
        * (
            _variance(baseline.samples) / len(baseline.samples)
            + _variance(treatment.samples) / len(treatment.samples)
        ).sqrt()
    )
    sign = Decimal(-1) if declaration.direction is ValueDirection.DECREASE_IS_BETTER else Decimal(1)
    improvement = sign * mean_delta
    conservative = max(improvement - margin, Decimal(0))
    if improvement - margin > 0:
        status = ValueClaimStatus.IMPROVED
    elif improvement + margin < 0:
        status = ValueClaimStatus.REGRESSED
    else:
        status = ValueClaimStatus.NO_SIGNIFICANT_CHANGE
    realized = status is ValueClaimStatus.IMPROVED
    return _settlement(
        declaration,
        status,
        baseline,
        treatment,
        mean_improvement=improvement,
        conservative=conservative if realized else Decimal(0),
        total=conservative * len(treatment.samples) if realized else Decimal(0),
        reasons=(),
    )


def _select_cohorts(
    cohorts: tuple[ValueCohortObservation, ...],
) -> tuple[ValueCohortObservation | None, ValueCohortObservation | None, str]:
    baselines = [item for item in cohorts if item.role is CohortRole.BASELINE]
    treatments = [item for item in cohorts if item.role is CohortRole.TREATMENT]
    if len(baselines) != 1 or len(treatments) != 1 or len(cohorts) != 2:
        return None, None, "exactly_one_baseline_and_one_treatment_required"
    return baselines[0], treatments[0], ""


def _scope_mismatch(
    declaration: ValueClaimDeclaration,
    baseline: ValueCohortObservation,
    treatment: ValueCohortObservation,
) -> tuple[str, ...]:
    reasons: list[str] = []
    for cohort in (baseline, treatment):
        if cohort.scenario_set_version != declaration.scenario_set_version:
            reasons.append(f"{cohort.role.value}_scenario_set_mismatch")
        if cohort.currency != declaration.currency:
            reasons.append(f"{cohort.role.value}_currency_mismatch")
        if cohort.observed_at < declaration.window_end:
            reasons.append(f"{cohort.role.value}_observed_before_window_end")
    return tuple(reasons)


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    return sum(values, Decimal(0)) / len(values)


def _variance(values: tuple[Decimal, ...]) -> Decimal:
    mean = _mean(values)
    return sum(((item - mean) ** 2 for item in values), Decimal(0)) / (len(values) - 1)


def _unsettled(
    declaration: ValueClaimDeclaration,
    status: ValueClaimStatus,
    reasons: tuple[str, ...],
    baseline: ValueCohortObservation | None,
    treatment: ValueCohortObservation | None,
) -> ValueClaimSettlement:
    return _settlement(
        declaration,
        status,
        baseline,
        treatment,
        mean_improvement=None,
        conservative=None,
        total=None,
        reasons=reasons,
    )


def _settlement(
    declaration: ValueClaimDeclaration,
    status: ValueClaimStatus,
    baseline: ValueCohortObservation | None,
    treatment: ValueCohortObservation | None,
    *,
    mean_improvement: Decimal | None,
    conservative: Decimal | None,
    total: Decimal | None,
    reasons: tuple[str, ...],
) -> ValueClaimSettlement:
    refs = tuple(
        dict.fromkeys(
            ref for cohort in (baseline, treatment) if cohort for ref in cohort.evidence_refs
        )
    )
    body = {
        "claim_id": declaration.claim_id,
        "workflow_ref": declaration.workflow_ref,
        "workflow_version": declaration.workflow_version,
        "status": status.value,
        "mean": None if mean_improvement is None else str(mean_improvement),
        "conservative": None if conservative is None else str(conservative),
        "total": None if total is None else str(total),
        "reasons": list(reasons),
        "evidence_refs": list(refs),
    }
    return ValueClaimSettlement(
        claim_id=declaration.claim_id,
        status=status,
        unit=declaration.unit,
        currency=declaration.currency,
        baseline_sample_count=len(baseline.samples) if baseline else 0,
        treatment_sample_count=len(treatment.samples) if treatment else 0,
        mean_improvement_per_event=mean_improvement,
        conservative_improvement_per_event=conservative,
        conservative_total_improvement=total,
        reason_codes=reasons,
        evidence_refs=refs,
        settlement_digest=content_digest(body),
    )


__all__ = [
    "CohortRole",
    "ObservationLane",
    "ValueClaimDeclaration",
    "ValueClaimSettlement",
    "ValueClaimStatus",
    "ValueCohortObservation",
    "ValueDirection",
    "ValueUnit",
    "settle_value_claim",
]
