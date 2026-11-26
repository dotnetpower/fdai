"""Extended time-simulated measurement: chaos demotion, invoice FinOps, T1 holdout, Zstd."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fdai_service_contracts.baseline_cohort import CohortArmFacts

from fdai.core.measurement.cost_effect_settlement import CostEffectSettlementService
from fdai.core.measurement.outcome_assurance import (
    OutcomeAssuranceProjection,
    OutcomeAssuranceScope,
    OutcomeVertical,
)
from fdai.core.measurement.pattern_growth import (
    HoldoutDecision,
    IntakeDecision,
    IntakeOutcome,
    OutcomeRecord,
    PatternCandidate,
    PatternValidationSample,
    TemporalHoldoutConfig,
    TemporalHoldoutValidator,
    evaluate_intake,
)
from fdai.core.measurement.regression import (
    GuardKind,
    GuardMetric,
    MeasurementSample,
    RegressionDecision,
    RegressionDetector,
    SuccessMetric,
)
from fdai.core.measurement.simulated_time_cohort import SimulatedTimeClock
from fdai.core.measurement.simulated_time_settlement import build_simulated_outcome_projection
from fdai.core.ontology_platform.archive_manifest import ArchiveSourcePartition
from fdai.core.ontology_platform.semantic_rollup import (
    RollupFactKind,
    RollupObservation,
    SemanticRollup,
    SemanticRollupPolicy,
    build_semantic_rollup,
)
from fdai.core.ontology_platform.zstd_codec import (
    ZstdArchiveBundle,
    ZstdCompressedArtifact,
    ZstdDictionaryArtifact,
    build_zstd_archive_bundle,
    compress_canonical_json,
    train_zstd_dictionary,
)
from fdai.shared.contracts.models import OntologyActionType
from fdai.shared.providers.cost_governance_decision import (
    CostCompletenessReceipt,
    CostEffectKind,
    CostEffectObservation,
    CostEpisodeSettlement,
    CostExpectedEffect,
    CostObservationLane,
    CostPostRecoveryObservation,
    CostSavingsEvidenceClass,
)
from fdai.shared.providers.state_store import StateStore


def _sha256(seed: str) -> str:
    return f"sha256:{hashlib.sha256(seed.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True, slots=True)
class GuardBreachDemotionSimulation:
    """Result of injecting a Day-15 guard breach and rollback spike (#13)."""

    regression_decision: RegressionDecision
    failed_settlement: CostEpisodeSettlement
    demoted_to_shadow: bool


@dataclass(frozen=True, slots=True)
class T1PatternHoldoutSimulation:
    """Result of 15-day intake + 15-day temporal holdout validation (#15)."""

    intake_decisions: tuple[IntakeDecision, ...]
    accepted_intake_count: int
    rejected_intake_count: int
    candidate: PatternCandidate
    holdout_decision: HoldoutDecision


@dataclass(frozen=True, slots=True)
class RollupAndZstdArchiveResult:
    """30-day temporal rollup + Zstd frame and dictionary compression receipts (#22 + Zstd)."""

    rollup: SemanticRollup
    dictionary: ZstdDictionaryArtifact
    frame_archive_bundle: ZstdArchiveBundle
    dict_archive_bundle: ZstdArchiveBundle
    small_record_no_dict: ZstdCompressedArtifact
    small_record_with_dict: ZstdCompressedArtifact


def simulate_guard_breach_auto_demotion(
    *,
    clock: SimulatedTimeClock,
    action_type_id: str = "remediate.right-size",
    scenario_set_version: str = "v2026.10",
) -> GuardBreachDemotionSimulation:
    """Inject a Day-15 SLO regression & guard breach and verify automatic demotion (#13)."""

    detector = RegressionDetector()
    sample = MeasurementSample(
        action_type_id=action_type_id,
        scenario_set_version=scenario_set_version,
        guard_metrics=(
            GuardMetric(GuardKind.POLICY_VIOLATION_ESCAPE, ceiling=0.0, observed=1.0),
            GuardMetric(GuardKind.ROLLBACK_RATE, ceiling=0.02, observed=0.12),
        ),
        success_metrics=(SuccessMetric("auto_resolution_rate", lower_ci=0.80, observed=0.65),),
    )
    decision = detector.evaluate(sample)
    predicted_at = clock.at_day(14, hour=8)
    evaluated_at = clock.at_day(15, hour=18)
    src_digest = _sha256("neg-finops-src")
    slo_effect = CostExpectedEffect(
        effect_id="ep-neg-service",
        kind=CostEffectKind.SERVICE,
        target_ref="res-vm-checkout-01",
        metric="service_availability_ratio",
        baseline_value=Decimal("0.9990"),
        acceptable_min=Decimal("0.9990"),
        acceptable_max=Decimal("1.0000"),
        predicted_at=predicted_at,
        horizon=timedelta(hours=12),
        telemetry_grace=timedelta(hours=2),
        source_digest=src_digest,
    )
    bad_obs = CostEffectObservation(
        observation_id="obs-neg-slo",
        effect_id=slo_effect.effect_id,
        effect_source_digest=src_digest,
        target_ref="res-vm-checkout-01",
        metric=slo_effect.metric,
        value=Decimal("0.9750"),
        observed_at=slo_effect.horizon_ends_at,
        lane=CostObservationLane.INDEPENDENT,
        source_authority="heimdall-slo-observer",
        evidence_digest=_sha256("obs-neg-ev"),
    )
    comp = CostCompletenessReceipt(
        effect_id=slo_effect.effect_id,
        effect_source_digest=src_digest,
        receipt_digest=_sha256("comp-neg"),
        complete=True,
        coverage_through_at=slo_effect.horizon_ends_at,
        lane=CostObservationLane.INDEPENDENT,
        source_authority="heimdall-completeness",
    )
    service = CostEffectSettlementService()
    frame_digest = _sha256("frame:ep-neg")
    initial = service.settle(
        episode_id="ep-neg-rightsize",
        decision_frame_digest=frame_digest,
        action_ref="action-run:ep-neg",
        action_revision=1,
        expected_effects=(slo_effect,),
        observations=(bad_obs,),
        completeness_receipts=(comp,),
        interventions=(),
        evaluated_at=evaluated_at,
        evidence_refs=(_sha256("settle-neg-ev"),),
        stop_condition_triggered=True,
    )
    if initial.rollback_request is None:
        raise RuntimeError("expected rollback_request on stop-condition settlement")
    recovery_obs = CostPostRecoveryObservation(
        recovery_request_id=initial.rollback_request.request_id,
        observed_at=evaluated_at + timedelta(minutes=30),
        restored=True,
        complete=True,
        lane=CostObservationLane.INDEPENDENT,
        source_authority="heimdall-recovery-observer",
        evidence_digest=_sha256("rec-neg-ev"),
    )
    settlement = service.settle(
        episode_id="ep-neg-rightsize",
        decision_frame_digest=frame_digest,
        action_ref="action-run:ep-neg",
        action_revision=1,
        expected_effects=(slo_effect,),
        observations=(bad_obs,),
        completeness_receipts=(comp,),
        interventions=(),
        evaluated_at=evaluated_at,
        evidence_refs=(_sha256("settle-neg-ev"),),
        stop_condition_triggered=True,
        post_recovery_observation=recovery_obs,
    )
    return GuardBreachDemotionSimulation(
        regression_decision=decision,
        failed_settlement=settlement,
        demoted_to_shadow=(
            decision.outcome.value == "guard_breach" and settlement.rollback_request is not None
        ),
    )


def simulate_invoice_allocated_settlements(
    *,
    clock: SimulatedTimeClock,
    billing_cycle_days: int = 35,
) -> tuple[CostEpisodeSettlement, ...]:
    """Settle all 6 FinOps target families with `INVOICE_ALLOCATED` + demand normalization (#14)."""

    targets = (
        ("inv-vm-rightsize", "res-vm-checkout-01", Decimal("1200.00"), Decimal("750.00")),
        ("inv-vmss-autoscale", "res-vmss-rec-01", Decimal("2400.00"), Decimal("1650.00")),
        ("inv-aks-pool-rightsize", "res-aks-checkout-01", Decimal("3100.00"), Decimal("2200.00")),
        ("inv-pg-storage-tier", "res-pg-orders-01", Decimal("950.00"), Decimal("600.00")),
        ("inv-sql-vcore-scale", "res-sql-billing-01", Decimal("1800.00"), Decimal("1150.00")),
        ("inv-log-retention-cap", "res-law-ops-01", Decimal("650.00"), Decimal("300.00")),
    )
    predicted_at = clock.at_day(1, hour=0)
    evaluated_at = clock.at_day(billing_cycle_days, hour=12)
    service = CostEffectSettlementService()
    results: list[CostEpisodeSettlement] = []
    for episode_id, target_ref, baseline_cost, observed_cost in targets:
        src_digest = _sha256(f"invoice-src:{episode_id}")
        cost_effect = CostExpectedEffect(
            effect_id=f"{episode_id}-cost",
            kind=CostEffectKind.COST,
            target_ref=target_ref,
            metric="monthly_invoice_allocated_cost_usd",
            baseline_value=baseline_cost,
            acceptable_min=observed_cost - Decimal("100.00"),
            acceptable_max=observed_cost + Decimal("50.00"),
            predicted_at=predicted_at,
            horizon=timedelta(days=30),
            telemetry_grace=timedelta(days=2),
            source_digest=src_digest,
            savings_evidence_class=CostSavingsEvidenceClass.INVOICE_ALLOCATED,
            currency="USD",
            baseline_window_digest=_sha256(f"inv-base:{episode_id}"),
            treatment_window_digest=_sha256(f"inv-treat:{episode_id}"),
            demand_normalization_digest=_sha256(f"weekday-weekend-demand:{episode_id}"),
            finalized_billing_receipt_digest=_sha256(f"final-billing-invoice:{episode_id}"),
            allocation_rule_digest=_sha256(f"cost-allocation-rule:{episode_id}"),
        )
        obs = CostEffectObservation(
            observation_id=f"obs-inv-{episode_id}",
            effect_id=cost_effect.effect_id,
            effect_source_digest=src_digest,
            target_ref=target_ref,
            metric=cost_effect.metric,
            value=observed_cost,
            observed_at=cost_effect.horizon_ends_at,
            lane=CostObservationLane.INDEPENDENT,
            source_authority="njord-invoice-reconciler",
            evidence_digest=_sha256(f"obs-inv-ev:{episode_id}"),
        )
        comp = CostCompletenessReceipt(
            effect_id=cost_effect.effect_id,
            effect_source_digest=src_digest,
            receipt_digest=_sha256(f"comp-inv:{episode_id}"),
            complete=True,
            coverage_through_at=cost_effect.horizon_ends_at,
            lane=CostObservationLane.INDEPENDENT,
            source_authority="heimdall-completeness",
        )
        results.append(
            service.settle(
                episode_id=episode_id,
                decision_frame_digest=_sha256(f"inv-frame:{episode_id}"),
                action_ref=f"action-run:{episode_id}",
                action_revision=1,
                expected_effects=(cost_effect,),
                observations=(obs,),
                completeness_receipts=(comp,),
                interventions=(),
                evaluated_at=evaluated_at,
                evidence_refs=(_sha256(f"inv-settle-ev:{episode_id}"),),
            )
        )
    return tuple(results)


def simulate_t1_pattern_growth_holdout(
    *,
    clock: SimulatedTimeClock,
) -> T1PatternHoldoutSimulation:
    """Simulate Day 1..15 pattern intake and Day 16..30 temporal holdout validation (#15)."""

    intake_records: list[OutcomeRecord] = []
    for day in range(1, 16):
        intake_records.append(
            OutcomeRecord(
                action_id=f"act-train-{day:02d}",
                action_type_id="ops.scale-out",
                observed_at=clock.at_day(day, hour=10),
                was_auto=True,
                was_verified=True,
                was_rolled_back=False,
            )
        )
    intake_records.append(
        OutcomeRecord(
            action_id="act-train-rb",
            action_type_id="ops.scale-out",
            observed_at=clock.at_day(5, hour=14),
            was_auto=True,
            was_verified=True,
            was_rolled_back=True,
        )
    )
    decisions = tuple(evaluate_intake(rec) for rec in intake_records)
    accepted = sum(1 for d in decisions if d.outcome is IntakeOutcome.ACCEPTED)
    rejected = len(decisions) - accepted
    candidate = PatternCandidate(
        pattern_id="pat-aks-cpu-saturation-scale-out",
        action_type_id="ops.scale-out",
        learned_at=clock.at_day(15, hour=23),
    )
    holdout_samples = tuple(
        PatternValidationSample(
            pattern_id=candidate.pattern_id,
            observed_at=clock.at_day(16 + (idx % 14), hour=(idx * 2) % 24),
            was_correct=(idx != 0),
        )
        for idx in range(25)
    )
    validator = TemporalHoldoutValidator(
        config=TemporalHoldoutConfig(min_samples=20, fp_rate_ceiling=0.05)
    )
    holdout_decision = validator.evaluate(candidate=candidate, holdout=holdout_samples)
    return T1PatternHoldoutSimulation(
        intake_decisions=decisions,
        accepted_intake_count=accepted,
        rejected_intake_count=rejected,
        candidate=candidate,
        holdout_decision=holdout_decision,
    )


def build_multi_vertical_outcome_projections(
    *,
    clock: SimulatedTimeClock,
    days: int,
    samples_per_day: int,
    action_types: Sequence[OntologyActionType],
    baseline_facts: CohortArmFacts,
    treatment_facts: CohortArmFacts,
    scenario_set_version: str = "v2026.10",
) -> dict[OutcomeVertical, OutcomeAssuranceProjection]:
    """Build OutcomeAssuranceProjections across Resilience, Change Safety, and FinOps (#21)."""

    base_proj = build_simulated_outcome_projection(
        window_start=clock.start_time,
        window_end=clock.at_day(days, hour=23),
        days=days,
        samples_per_day=samples_per_day,
        action_types=action_types,
        baseline_facts=baseline_facts,
        treatment_facts=treatment_facts,
        scenario_set_version=scenario_set_version,
    )
    return {
        vertical: OutcomeAssuranceProjection(
            scope=OutcomeAssuranceScope(
                scope_ref=f"scope:simulated-enterprise-{vertical.value}",
                service_refs=base_proj.scope.service_refs,
                workload_refs=base_proj.scope.workload_refs,
                vertical=vertical,
            ),
            window=base_proj.window,
            readiness=base_proj.readiness,
            alignment=base_proj.alignment,
            outcomes=base_proj.outcomes,
            guards=base_proj.guards,
            provenance=base_proj.provenance,
        )
        for vertical in (
            OutcomeVertical.RESILIENCE,
            OutcomeVertical.CHANGE_SAFETY,
            OutcomeVertical.COST_GOVERNANCE,
        )
    }


def simulate_rollup_and_zstd_archive_lifecycle(
    *,
    clock: SimulatedTimeClock,
    days: int = 30,
    ontology_release_digest: str,
) -> RollupAndZstdArchiveResult:
    """Aggregate 30-day temporal rollups and package into verified Zstd archives (#22 + Zstd)."""

    policy = SemanticRollupPolicy(
        semantic_id="utilization.cpu.p95",
        revision="1.0.0",
        ontology_release_digest=ontology_release_digest,
        fact_kind=RollupFactKind.GAUGE,
        expected_interval_seconds=86400,
        statistics=(
            "count",
            "sum",
            "minimum",
            "maximum",
            "average",
            "extrema_timestamps",
            "time_coverage",
        ),
    )
    part_digest = _sha256("rollup-partition-30d")
    observations: list[RollupObservation] = []
    for day in range(days):
        t0 = clock.at_day(day, hour=0)
        t1 = clock.at_day(day + 1, hour=0)
        observations.append(
            RollupObservation(
                observation_id=f"rollup-obs-{day:03d}",
                semantic_id=policy.semantic_id,
                fact_kind=RollupFactKind.GAUGE,
                source_id="heimdall-metrics",
                source_revision="rev-1",
                source_partition_digest=part_digest,
                generation_ref="gen-30d",
                ontology_release_digest=ontology_release_digest,
                interval_start=t0,
                interval_end=t1,
                effective_at=t0 + timedelta(hours=12),
                event_at=t0 + timedelta(hours=12),
                recorded_at=t1,
                value=Decimal(str(45 + (day % 25))),
                complete=True,
                conflict_count=0,
            )
        )
    w_start = clock.start_time
    w_end = clock.at_day(days, hour=0)
    rollup = build_semantic_rollup(
        policy,
        tuple(observations),
        window_start=w_start,
        window_end=w_end,
    )
    sample_records = [
        {
            "id": f"res-aks-node-{idx:04d}",
            "object_type": "Resource",
            "type": "kubernetes-node-pool",
            "location": "koreacentral",
            "service_ref": "svc-checkout-api",
            "workload_ref": "wl-checkout-aks",
            "ontology_release_digest": ontology_release_digest,
        }
        for idx in range(64)
    ]
    zdict = train_zstd_dictionary(sample_records, dict_size=4096)
    small_no_dict = compress_canonical_json(sample_records[0], level=3)
    small_with_dict = compress_canonical_json(sample_records[0], level=3, dictionary=zdict)
    archive_payload = {
        "rollup_digest": rollup.digest,
        "statistics": rollup.statistics_json,
        "records": sample_records,
    }
    partitions = (
        ArchiveSourcePartition(
            partition_id="part-30d-01",
            content_digest=part_digest,
            interval_start=w_start,
            interval_end=w_end,
            object_count=len(sample_records),
            relationship_count=128,
            schema_version="1.0.0",
            ontology_release_digest=ontology_release_digest,
            complete=True,
            conflict_count=0,
        ),
    )
    frame_bundle = build_zstd_archive_bundle(
        partitions,
        archive_payload,
        created_at=w_end,
        dictionary=None,
    )
    dict_bundle = build_zstd_archive_bundle(
        partitions,
        archive_payload,
        created_at=w_end,
        dictionary=zdict,
    )
    return RollupAndZstdArchiveResult(
        rollup=rollup,
        dictionary=zdict,
        frame_archive_bundle=frame_bundle,
        dict_archive_bundle=dict_bundle,
        small_record_no_dict=small_no_dict,
        small_record_with_dict=small_with_dict,
    )


async def seed_simulated_enterprise_state_store(
    store: StateStore,
    *,
    projections: Mapping[OutcomeVertical, OutcomeAssuranceProjection],
    archive_result: RollupAndZstdArchiveResult,
) -> tuple[str, ...]:
    """Persist simulated multi-vertical projections and Zstd archive metadata (#11, #20)."""

    written_keys: list[str] = []
    now_iso = datetime.now(tz=UTC).isoformat()
    for vertical, proj in sorted(projections.items(), key=lambda kv: kv[0].value):
        key = f"simulated-outcome-assurance:{vertical.value}"
        await store.write_state_with_audit_if_absent(
            key,
            proj.to_dict(),
            {
                "actor": "fdai.simulated-seeder",
                "action_kind": "simulation.outcome_assurance.seeded",
                "vertical": vertical.value,
                "recorded_at": now_iso,
            },
        )
        written_keys.append(key)
    archive_key = f"simulated-zstd-archive:{archive_result.dict_archive_bundle.manifest.digest}"
    await store.write_state_with_audit_if_absent(
        archive_key,
        {
            "manifest_digest": archive_result.dict_archive_bundle.manifest.digest,
            "compression_profile": archive_result.dict_archive_bundle.artifact.profile,
            "raw_bytes": archive_result.dict_archive_bundle.artifact.raw_byte_length,
            "compressed_bytes": archive_result.dict_archive_bundle.artifact.compressed_byte_length,
            "space_savings_pct": archive_result.dict_archive_bundle.artifact.space_savings_pct,
        },
        {
            "actor": "fdai.simulated-seeder",
            "action_kind": "simulation.zstd_archive.seeded",
            "recorded_at": now_iso,
        },
    )
    written_keys.append(archive_key)
    return tuple(written_keys)
