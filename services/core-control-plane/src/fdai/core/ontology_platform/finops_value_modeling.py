"""Business semantic layer and FinOps value modeling (Items 12-16).

Provides:
12. ``CostObservationOntologyProjector``: projects provider ``CostObservation`` records into
    the runtime ontology instance graph with ``cost_observation_targets_resource`` links.
13. ``decision.budget_burn_risk``: forecasts end-of-period spend against ``Budget`` and
    ``CostObjective`` bounds.
14. ``score_business_service_criticality``: multi-objective criticality scoring combining
    base criticality with ``ServiceObjective`` (availability target), ``RecoveryObjective``
    (RTO minutes), and ``CostObjective`` bindings.
15. ``filter_safe_sizing_recommendations``: combines ``SizingRecommendation`` candidates with
    change-window, SLO headroom, and blast-radius safety checks.
16. ``evaluate_unit_economics``: computes cost-per-unit throughput efficiency and blocks
    false savings caused by throughput drop or SLO degradation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from math import isfinite
from pathlib import Path
from typing import Final

from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyFunctionKind,
    OntologyFunctionType,
)
from fdai.shared.providers.cost_governance import CostObservation as ProviderCostObservation
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyLinkRecord,
    OntologyObjectRecord,
)

from .decision_functions import DECISION_PURPOSE

BUDGET_BURN_RISK_FUNCTION_NAME: Final = "decision.budget_burn_risk"
_BASE_WEIGHTS: Final = {"low": 1, "medium": 2, "high": 4, "critical": 8}


class CostObservationOntologyProjector:
    """Item 12: Project provider CostObservation facts into the ontology instance graph."""

    def __init__(self, store: OntologyInstanceStore, *, metric: str = "cost") -> None:
        if not metric.strip():
            raise ValueError("CostObservationOntologyProjector.metric MUST be non-empty")
        self._store = store
        self._metric = metric.strip()

    async def project_observation(
        self,
        observation: ProviderCostObservation,
        *,
        target_resource_ref: str,
    ) -> OntologyObjectRecord:
        if not target_resource_ref.strip():
            raise ValueError("target_resource_ref MUST be non-empty")
        target = await self._store.get_object(target_resource_ref)
        if target is None or target.object_type != "Resource":
            raise LookupError(f"Target Resource {target_resource_ref!r} is absent from ontology")
        complete = observation.completeness == Decimal("1")
        record = OntologyObjectRecord(
            id=observation.observation_id,
            object_type="CostObservation",
            properties={
                "id": observation.observation_id,
                "target_ref": target_resource_ref,
                "metric": self._metric,
                "value": float(observation.amount),
                "currency": observation.currency,
                "period_start": observation.event_start_at,
                "period_end": observation.event_end_at,
                "observed_at": observation.observed_at,
                "evidence_ref": observation.evidence_digest,
                "source_revision": observation.ontology_release_id,
                "source_authority_ref": observation.source_authority,
                "complete": complete,
                "synthetic": False,
            },
        )
        await self._store.upsert_object(record)
        await self._store.upsert_link(
            OntologyLinkRecord(
                link_type="cost_observation_targets_resource",
                from_id=record.id,
                to_id=target_resource_ref,
            )
        )
        return record


@dataclass(frozen=True, slots=True)
class BudgetBurnEvidence:
    """Item 13: Observed spend-to-date, daily burn rate, and remaining period days."""

    budget_limit_amount: Decimal | None
    spent_to_date_amount: Decimal | None
    daily_burn_rate: Decimal | None
    remaining_days: int | None
    currency: str | None
    observed_at: datetime


def assess_budget_burn_risk(
    evidence: BudgetBurnEvidence,
    *,
    target_ref: str,
    max_projected_utilization_ratio: float = 1.0,
) -> dict[str, object]:
    """Item 13: Forecast end-of-period budget utilization and gate on overrun risk."""

    if not isfinite(max_projected_utilization_ratio) or max_projected_utilization_ratio <= 0.0:
        raise ValueError("max_projected_utilization_ratio MUST be positive")
    reasons: list[str] = []
    limit = evidence.budget_limit_amount
    spent = evidence.spent_to_date_amount
    burn = evidence.daily_burn_rate
    days = evidence.remaining_days
    if limit is None or not limit.is_finite() or limit <= Decimal(0):
        reasons.append("budget_limit_unobserved")
    if spent is None or not spent.is_finite() or spent < Decimal(0):
        reasons.append("spent_to_date_unobserved")
    if burn is None or not burn.is_finite() or burn < Decimal(0):
        reasons.append("daily_burn_rate_unobserved")
    if days is None or days < 0:
        reasons.append("remaining_days_unobserved")
    if not evidence.currency or not evidence.currency.strip():
        reasons.append("currency_unobserved")
    complete = not reasons
    projected: Decimal | None = None
    utilization: float | None = None
    if (
        complete
        and limit is not None
        and spent is not None
        and burn is not None
        and days is not None
    ):
        projected = spent + (burn * Decimal(days))
        utilization = round(float(projected / limit), 6)
    tier = (
        "unknown"
        if not complete or utilization is None
        else (
            "critical"
            if utilization > 1.1
            else "high"
            if utilization > 1.0
            else "medium"
            if utilization > 0.85
            else "low"
        )
    )
    satisfied = (
        complete and utilization is not None and utilization <= max_projected_utilization_ratio
    )
    return {
        "schema_version": "1.0.0",
        "function": BUDGET_BURN_RISK_FUNCTION_NAME,
        "target_ref": target_ref,
        "tier": tier,
        "complete": complete,
        "gate_satisfied": satisfied,
        "observed_at": evidence.observed_at.isoformat(),
        "reason_codes": sorted(reasons),
        "projected_total_amount": None if projected is None else str(projected),
        "projected_utilization_ratio": utilization,
        "currency": evidence.currency if complete else None,
        "execution_authority": False,
        "mutation_authority": False,
    }


def budget_burn_risk_function_type() -> OntologyFunctionType:
    props: dict[str, object] = {
        "schema_version": {"const": "1.0.0"},
        "function": {"type": "string"},
        "target_ref": {"type": "string"},
        "tier": {"type": "string", "enum": ["low", "medium", "high", "critical", "unknown"]},
        "complete": {"type": "boolean"},
        "gate_satisfied": {"type": "boolean"},
        "observed_at": {"type": "string"},
        "reason_codes": {"type": "array", "items": {"type": "string"}},
        "projected_total_amount": {"type": ["string", "null"]},
        "projected_utilization_ratio": {"type": ["number", "null"]},
        "currency": {"type": ["string", "null"]},
        "execution_authority": {"const": False},
        "mutation_authority": {"const": False},
    }
    return OntologyFunctionType(
        name=BUDGET_BURN_RISK_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.DERIVE,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["max_projected_utilization_ratio"],
            "properties": {
                "max_projected_utilization_ratio": {
                    "type": "number",
                    "minimum": 0.1,
                    "maximum": 5.0,
                }
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": sorted(props),
            "properties": props,
        },
        read_sets=[],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=[DECISION_PURPOSE],
        timeout_seconds=5,
        cpu_millis=250,
        memory_bytes=67_108_864,
        max_output_bytes=65_536,
        network_allowed=False,
        credentials_allowed=False,
    )


@dataclass(frozen=True, slots=True)
class MultiObjectiveCriticalityScore:
    """Item 14: Multi-dimensional criticality score for a BusinessService."""

    service_ref: str
    base_criticality: str
    availability_target_pct: float | None
    rto_target_minutes: int | None
    has_cost_objective: bool
    composite_weight: int
    effective_tier: str


def score_business_service_criticality(
    *,
    service_ref: str,
    base_criticality: str,
    availability_target_pct: float | None = None,
    rto_target_minutes: int | None = None,
    has_cost_objective: bool = False,
) -> MultiObjectiveCriticalityScore:
    """Item 14: Combine base criticality with SLO availability, RTO, and cost objectives."""

    clean = base_criticality.strip().lower()
    if clean not in _BASE_WEIGHTS:
        raise ValueError(f"Unsupported base_criticality: {base_criticality!r}")
    weight = _BASE_WEIGHTS[clean]
    if availability_target_pct is not None:
        if not 0.0 < availability_target_pct <= 100.0:
            raise ValueError("availability_target_pct MUST be in (0, 100]")
        if availability_target_pct >= 99.99:
            weight += 4
        elif availability_target_pct >= 99.9:
            weight += 2
    if rto_target_minutes is not None:
        if rto_target_minutes < 1:
            raise ValueError("rto_target_minutes MUST be >= 1")
        if rto_target_minutes <= 15:
            weight += 4
        elif rto_target_minutes <= 60:
            weight += 2
    if has_cost_objective:
        weight += 1
    tier = (
        "critical" if weight >= 8 else "high" if weight >= 4 else "medium" if weight >= 2 else "low"
    )
    return MultiObjectiveCriticalityScore(
        service_ref=service_ref,
        base_criticality=clean,
        availability_target_pct=availability_target_pct,
        rto_target_minutes=rto_target_minutes,
        has_cost_objective=has_cost_objective,
        composite_weight=weight,
        effective_tier=tier,
    )


@dataclass(frozen=True, slots=True)
class SizingCandidateInput:
    """Item 15: One SizingRecommendation candidate with its safety context."""

    recommendation_id: str
    target_resource_ref: str
    estimated_monthly_savings: Decimal
    currency: str
    confidence: float
    in_change_window: bool
    slo_headroom_ok: bool
    blast_radius_tier: str


@dataclass(frozen=True, slots=True)
class SafeSizingFilterReport:
    """Item 15: Filtered safe right-sizing recommendations and rejected reasons."""

    admitted: tuple[SizingCandidateInput, ...]
    rejected_reasons: dict[str, tuple[str, ...]]
    total_admitted_monthly_savings: Decimal
    currency: str | None


def filter_safe_sizing_recommendations(
    candidates: Sequence[SizingCandidateInput],
    *,
    min_confidence: float = 0.8,
    allowed_blast_tiers: frozenset[str] = frozenset({"low", "medium"}),
) -> SafeSizingFilterReport:
    """Item 15: Admit only SizingRecommendations that satisfy SLO, window, and blast safety."""

    admitted: list[SizingCandidateInput] = []
    rejected: dict[str, tuple[str, ...]] = {}
    currencies = {c.currency for c in candidates}
    if len(currencies) > 1:
        raise ValueError("SizingRecommendation batch MUST share one currency")
    for cand in candidates:
        reasons: list[str] = []
        if cand.confidence < min_confidence:
            reasons.append("confidence_below_floor")
        if not cand.in_change_window:
            reasons.append("outside_change_window")
        if not cand.slo_headroom_ok:
            reasons.append("insufficient_slo_headroom")
        if cand.blast_radius_tier not in allowed_blast_tiers:
            reasons.append("blast_radius_exceeds_ceiling")
        if cand.estimated_monthly_savings <= Decimal(0):
            reasons.append("non_positive_savings")
        if reasons:
            rejected[cand.recommendation_id] = tuple(reasons)
        else:
            admitted.append(cand)
    ordered = tuple(
        sorted(
            admitted,
            key=lambda item: (-item.estimated_monthly_savings, item.recommendation_id),
        )
    )
    total = sum((item.estimated_monthly_savings for item in ordered), Decimal(0))
    return SafeSizingFilterReport(
        admitted=ordered,
        rejected_reasons=rejected,
        total_admitted_monthly_savings=total,
        currency=next(iter(currencies)) if currencies else None,
    )


@dataclass(frozen=True, slots=True)
class UnitEconomicsWindow:
    """Item 16: Cost, throughput, and SLO health for one baseline or treatment window."""

    total_cost_amount: Decimal
    throughput_units: Decimal
    slo_violated: bool = False


@dataclass(frozen=True, slots=True)
class UnitEconomicsVerdict:
    """Item 16: Unit cost comparison that blocks false savings from degraded throughput/SLO."""

    baseline_cost_per_unit: Decimal
    treatment_cost_per_unit: Decimal
    unit_cost_reduction_ratio: float
    throughput_retained: bool
    valid_efficiency_gain: bool
    reason_code: str


def evaluate_unit_economics(
    *,
    baseline: UnitEconomicsWindow,
    treatment: UnitEconomicsWindow,
    min_throughput_retention_ratio: Decimal = Decimal("0.90"),
) -> UnitEconomicsVerdict:
    """Item 16: Verify unit-cost reduction without throughput collapse or SLO breach."""

    if baseline.throughput_units <= Decimal(0) or treatment.throughput_units <= Decimal(0):
        raise ValueError("throughput_units MUST be positive")
    if baseline.total_cost_amount < Decimal(0) or treatment.total_cost_amount < Decimal(0):
        raise ValueError("total_cost_amount MUST be non-negative")
    base_unit = baseline.total_cost_amount / baseline.throughput_units
    treat_unit = treatment.total_cost_amount / treatment.throughput_units
    reduction = (
        0.0 if base_unit == Decimal(0) else round(float((base_unit - treat_unit) / base_unit), 6)
    )
    retained = (
        treatment.throughput_units / baseline.throughput_units >= min_throughput_retention_ratio
    )
    if treatment.slo_violated:
        return UnitEconomicsVerdict(
            baseline_cost_per_unit=base_unit,
            treatment_cost_per_unit=treat_unit,
            unit_cost_reduction_ratio=reduction,
            throughput_retained=retained,
            valid_efficiency_gain=False,
            reason_code="blocked_by_slo_violation",
        )
    if not retained:
        return UnitEconomicsVerdict(
            baseline_cost_per_unit=base_unit,
            treatment_cost_per_unit=treat_unit,
            unit_cost_reduction_ratio=reduction,
            throughput_retained=False,
            valid_efficiency_gain=False,
            reason_code="blocked_by_throughput_drop",
        )
    improved = treat_unit < base_unit
    return UnitEconomicsVerdict(
        baseline_cost_per_unit=base_unit,
        treatment_cost_per_unit=treat_unit,
        unit_cost_reduction_ratio=reduction,
        throughput_retained=True,
        valid_efficiency_gain=improved,
        reason_code="unit_cost_improved" if improved else "no_unit_cost_improvement",
    )


__all__ = [
    "BUDGET_BURN_RISK_FUNCTION_NAME",
    "BudgetBurnEvidence",
    "CostObservationOntologyProjector",
    "MultiObjectiveCriticalityScore",
    "SafeSizingFilterReport",
    "SizingCandidateInput",
    "UnitEconomicsVerdict",
    "UnitEconomicsWindow",
    "assess_budget_burn_risk",
    "budget_burn_risk_function_type",
    "evaluate_unit_economics",
    "filter_safe_sizing_recommendations",
    "score_business_service_criticality",
]
