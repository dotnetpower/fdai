"""Multi-day FinOps settlement and Outcome Assurance builders for simulated time."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from fdai_service_contracts.baseline_cohort import CohortArmFacts

from fdai.core.measurement.cost_effect_settlement import CostEffectSettlementService
from fdai.core.measurement.outcome_assurance import (
    ConfidenceInterval,
    ControlAssuranceState,
    ControlAssuranceSummary,
    FinalizedOutcomeEvent,
    GuardEvaluation,
    OutcomeAssuranceProjection,
    OutcomeAssuranceScope,
    OutcomeAssuranceWindow,
    OutcomeEvidenceState,
    OutcomeMeasurement,
    OutcomeMeasurementObservation,
    OutcomeProvenance,
    OutcomeVertical,
    ReadinessFacet,
    ReadinessFacetSnapshot,
    ReadinessFacetState,
    summarize_objective_attribution,
)
from fdai.shared.contracts.models import OntologyActionType
from fdai.shared.providers.cost_governance_decision import (
    CostCompletenessReceipt,
    CostEffectKind,
    CostEffectObservation,
    CostEpisodeSettlement,
    CostExpectedEffect,
    CostObservationLane,
    CostSavingsEvidenceClass,
)


def _sha256(seed: str) -> str:
    return f"sha256:{hashlib.sha256(seed.encode('utf-8')).hexdigest()}"


def simulate_finops_multi_day_settlements(
    *,
    predicted_at: datetime,
    evaluated_at: datetime,
    horizon_days: int,
) -> tuple[CostEpisodeSettlement, ...]:
    """Settle all 6 FinOps target families after advancing simulated time past horizon."""

    targets = (
        ("ep-vm-rightsize", "res-vm-checkout-01", Decimal("1200.00"), Decimal("750.00")),
        ("ep-vmss-autoscale", "res-vmss-rec-01", Decimal("2400.00"), Decimal("1650.00")),
        ("ep-aks-pool-rightsize", "res-aks-checkout-01", Decimal("3100.00"), Decimal("2200.00")),
        ("ep-pg-storage-tier", "res-pg-orders-01", Decimal("950.00"), Decimal("600.00")),
        ("ep-sql-vcore-scale", "res-sql-billing-01", Decimal("1800.00"), Decimal("1150.00")),
        ("ep-log-retention-cap", "res-law-ops-01", Decimal("650.00"), Decimal("300.00")),
    )
    service = CostEffectSettlementService()
    settlements: list[CostEpisodeSettlement] = []
    for episode_id, target_ref, baseline_cost, observed_cost in targets:
        src_digest = _sha256(f"finops-src:{episode_id}")
        cost_effect = CostExpectedEffect(
            effect_id=f"{episode_id}-cost",
            kind=CostEffectKind.COST,
            target_ref=target_ref,
            metric="daily_amortized_cost_usd",
            baseline_value=baseline_cost,
            acceptable_min=observed_cost - Decimal("100.00"),
            acceptable_max=observed_cost + Decimal("50.00"),
            predicted_at=predicted_at,
            horizon=timedelta(days=horizon_days),
            telemetry_grace=timedelta(hours=6),
            source_digest=src_digest,
            savings_evidence_class=CostSavingsEvidenceClass.VERIFIED_RUN_RATE,
            currency="USD",
            baseline_window_digest=_sha256(f"base-win:{episode_id}"),
            treatment_window_digest=_sha256(f"treat-win:{episode_id}"),
            demand_normalization_digest=_sha256(f"demand-norm:{episode_id}"),
        )
        slo_effect = CostExpectedEffect(
            effect_id=f"{episode_id}-service",
            kind=CostEffectKind.SERVICE,
            target_ref=target_ref,
            metric="service_availability_ratio",
            baseline_value=Decimal("0.9990"),
            acceptable_min=Decimal("0.9990"),
            acceptable_max=Decimal("1.0000"),
            predicted_at=predicted_at,
            horizon=timedelta(days=horizon_days),
            telemetry_grace=timedelta(hours=6),
            source_digest=src_digest,
        )
        observations = (
            CostEffectObservation(
                observation_id=f"obs-cost-{episode_id}",
                effect_id=cost_effect.effect_id,
                effect_source_digest=src_digest,
                target_ref=target_ref,
                metric=cost_effect.metric,
                value=observed_cost,
                observed_at=cost_effect.horizon_ends_at,
                lane=CostObservationLane.INDEPENDENT,
                source_authority="heimdall-cost-observer",
                evidence_digest=_sha256(f"obs-ev-cost:{episode_id}"),
            ),
            CostEffectObservation(
                observation_id=f"obs-slo-{episode_id}",
                effect_id=slo_effect.effect_id,
                effect_source_digest=src_digest,
                target_ref=target_ref,
                metric=slo_effect.metric,
                value=Decimal("0.9995"),
                observed_at=slo_effect.horizon_ends_at,
                lane=CostObservationLane.INDEPENDENT,
                source_authority="heimdall-slo-observer",
                evidence_digest=_sha256(f"obs-ev-slo:{episode_id}"),
            ),
        )
        completeness = (
            CostCompletenessReceipt(
                effect_id=cost_effect.effect_id,
                effect_source_digest=src_digest,
                receipt_digest=_sha256(f"comp-cost:{episode_id}"),
                complete=True,
                coverage_through_at=cost_effect.horizon_ends_at,
                lane=CostObservationLane.INDEPENDENT,
                source_authority="heimdall-completeness",
            ),
            CostCompletenessReceipt(
                effect_id=slo_effect.effect_id,
                effect_source_digest=src_digest,
                receipt_digest=_sha256(f"comp-slo:{episode_id}"),
                complete=True,
                coverage_through_at=slo_effect.horizon_ends_at,
                lane=CostObservationLane.INDEPENDENT,
                source_authority="heimdall-completeness",
            ),
        )
        settlements.append(
            service.settle(
                episode_id=episode_id,
                decision_frame_digest=_sha256(f"frame:{episode_id}"),
                action_ref=f"action-run:{episode_id}",
                action_revision=1,
                expected_effects=(cost_effect, slo_effect),
                observations=observations,
                completeness_receipts=completeness,
                interventions=(),
                evaluated_at=evaluated_at,
                evidence_refs=(_sha256(f"settle-ev:{episode_id}"),),
            )
        )
    return tuple(settlements)


def build_simulated_outcome_projection(
    *,
    window_start: datetime,
    window_end: datetime,
    days: int,
    samples_per_day: int,
    action_types: Sequence[OntologyActionType],
    baseline_facts: CohortArmFacts,
    treatment_facts: CohortArmFacts,
    scenario_set_version: str,
) -> OutcomeAssuranceProjection:
    """Build a 100%-attributed Outcome Assurance projection over the simulated window."""

    total_events = days * samples_per_day
    objectives = ("obj-slo-checkout", "obj-rto-checkout", "obj-cost-checkout")
    finalized: list[FinalizedOutcomeEvent] = []
    obs_list: list[OutcomeMeasurementObservation] = []
    for idx in range(total_events):
        ev_time = window_start + timedelta(
            days=idx // samples_per_day,
            hours=(idx % samples_per_day) * 4 + 2,
        )
        obj_ref = objectives[idx % len(objectives)]
        event_id = f"sim-event-{idx:04d}"
        finalized.append(
            FinalizedOutcomeEvent(
                event_id=event_id,
                finalized_at=ev_time,
                decision_case_id=f"case-{idx:04d}",
                protected_objective_ref=obj_ref,
                workflow_ref="workflow:autonomous-ops@1.0.0",
                action_type_id=action_types[idx % len(action_types)].name,
                action_run_id=f"run-{idx:04d}",
                observed_outcome_ref=f"outcome-{idx:04d}",
                evidence_refs=(_sha256(f"oa-event:{idx:04d}"),),
            )
        )
        obs_list.append(
            OutcomeMeasurementObservation(
                event_id=event_id,
                objective_ref=obj_ref,
                metric="mttr_seconds",
                observation_id=f"oa-obs-{idx:04d}",
                observed_at=ev_time,
                recorded_at=ev_time + timedelta(seconds=30),
                value=240.0,
                evidence_ref=_sha256(f"oa-obs-ev:{idx:04d}"),
            )
        )
    alignment = summarize_objective_attribution(
        finalized_events=tuple(finalized),
        observations=tuple(obs_list),
    )
    readiness = tuple(
        ReadinessFacetSnapshot(
            facet=facet,
            state=ReadinessFacetState.READY,
            evidence_refs=(_sha256(f"readiness:{facet.value}"),),
            observed_at=window_end,
            expires_at=window_end + timedelta(days=7),
        )
        for facet in ReadinessFacet
    )
    base_by_id = {m.metric_id: m for m in baseline_facts.metrics}
    outcomes = tuple(
        OutcomeMeasurement(
            objective_ref=objectives[idx % len(objectives)],
            metric=m.metric_id,
            state=OutcomeEvidenceState.MEASURED,
            current_value=m.absolute_value,
            baseline_value=base_by_id[m.metric_id].absolute_value,
            target_value=m.absolute_value,
            unit=(
                "USD" if "usd" in m.metric_id else ("ratio" if "rate" in m.metric_id else "seconds")
            ),
            sample_size=m.sample_size,
            confidence_interval=ConfidenceInterval(low=m.lower_bound, high=m.upper_bound),
            source_time=window_end,
            evidence_refs=(_sha256(f"oa-metric:{m.metric_id}"),),
        )
        for idx, m in enumerate(treatment_facts.metrics)
    )
    guards = ControlAssuranceSummary(
        state=ControlAssuranceState.HEALTHY,
        guard_evaluations=tuple(
            GuardEvaluation(
                guard_id=g.guard_id,
                threshold=0.0,
                observed_value=float(g.observed_basis_points),
                passed=g.observed_basis_points == 0,
                evidence_ref=_sha256(f"oa-guard:{g.guard_id}"),
            )
            for g in treatment_facts.guards
        ),
        policy_escape_count=0,
        evidence_refs=(_sha256("oa-control-assurance"),),
    )
    return OutcomeAssuranceProjection(
        scope=OutcomeAssuranceScope(
            scope_ref="scope:simulated-enterprise-prod",
            service_refs=("svc-checkout-api", "svc-order-processor", "svc-recommendation-engine"),
            workload_refs=("wl-checkout-aks", "wl-order-worker", "wl-rec-gpu-pool"),
            vertical=OutcomeVertical.RESILIENCE,
        ),
        window=OutcomeAssuranceWindow(
            start=window_start,
            end=window_end,
            scenario_set_version=scenario_set_version,
        ),
        readiness=readiness,
        alignment=alignment,
        outcomes=outcomes,
        guards=guards,
        provenance=OutcomeProvenance(
            source_names=("fdai.simulated-time-cohort", "fdai.measurement", "fdai.ontology"),
            as_of=window_end,
            synthetic=False,
        ),
    )
