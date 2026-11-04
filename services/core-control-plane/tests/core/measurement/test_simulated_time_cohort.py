"""Tests for the time-simulated multi-day cohort and measurement engine."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fdai.core.measurement import (
    ControlAssuranceState,
    ObjectiveAttributionState,
    OutcomeEvidenceState,
    ReadinessFacet,
    ReadinessFacetState,
    SimulatedTimeClock,
    load_cohort_claim_policy,
    run_simulated_multi_day_cohort,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.cost_governance_decision import CostSettlementStatus

REPO_ROOT = Path(__file__).resolve().parents[5]


def test_simulated_time_clock_advances_across_multi_day_horizon() -> None:
    start = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    clock = SimulatedTimeClock(start)

    assert clock.now() == start
    assert clock.at_day(14, hour=6) == datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
    assert clock.advance_days(30) == datetime(2026, 10, 31, 0, 0, tzinfo=UTC)
    assert clock.advance_hours(12) == datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


def test_simulated_multi_day_cohort_executes_30_days_of_sre_finops_and_promotion() -> None:
    policy = load_cohort_claim_policy(REPO_ROOT / "config" / "sre-cohort-claim-policy.json")
    catalog = load_action_type_catalog(
        REPO_ROOT / "rule-catalog" / "action-types",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=None,
    )
    target_names = {
        "ops.scale-out",
        "remediate.right-size",
        "ops.deallocate-vm",
        "remediate.set-retention-policy",
        "remediate.remove-orphan-resource",
        "ops.restart-service",
    }
    selected_actions = tuple(item for item in catalog if item.name in target_names)
    assert len(selected_actions) == 6

    result = run_simulated_multi_day_cohort(
        policy=policy,
        action_types=selected_actions,
        days=30,
        samples_per_day=4,
    )

    assert result.simulated_days == 30
    assert result.total_events == 120
    assert result.baseline_facts.sample_count == 120
    assert result.treatment_facts.sample_count == 120

    base_metrics = {m.metric_id: m for m in result.baseline_facts.metrics}
    treat_metrics = {m.metric_id: m for m in result.treatment_facts.metrics}
    assert set(treat_metrics) == {
        "auto_resolution_rate",
        "change_lead_time_seconds",
        "cost_per_unit_usd",
        "human_touchpoints_per_100_events",
        "mttr_seconds",
    }
    assert (
        treat_metrics["auto_resolution_rate"].lower_bound
        > base_metrics["auto_resolution_rate"].upper_bound
    )
    assert treat_metrics["mttr_seconds"].upper_bound < base_metrics["mttr_seconds"].lower_bound
    assert (
        treat_metrics["change_lead_time_seconds"].upper_bound
        < base_metrics["change_lead_time_seconds"].lower_bound
    )
    assert (
        treat_metrics["human_touchpoints_per_100_events"].upper_bound
        < base_metrics["human_touchpoints_per_100_events"].lower_bound
    )
    assert (
        treat_metrics["cost_per_unit_usd"].upper_bound
        < base_metrics["cost_per_unit_usd"].lower_bound
    )
    assert all(g.observed_basis_points == 0 for g in result.treatment_facts.guards)

    assert len(result.promotion_receipts) == 6
    assert result.all_promotions_ready is True
    for receipt in result.promotion_receipts:
        assert receipt.ready is True
        assert receipt.gaps == ()
        assert receipt.live_observation_days >= 30
        assert receipt.live_shadow_samples >= 120
        assert receipt.benchmark_samples >= 20
        assert receipt.policy_escapes == 0
        assert receipt.rollback_rate == 0.0
        assert receipt.recurrence_rate == 0.0

    assert len(result.finops_settlements) == 6
    assert result.all_settlements_verified is True
    assert result.total_realized_savings_usd == Decimal("3450.00")
    for settlement in result.finops_settlements:
        assert settlement.terminal is True
        assert settlement.rollback_request is None
        assert all(eff.status is CostSettlementStatus.VERIFIED for eff in settlement.effects)

    projection = result.outcome_projection
    assert len(projection.readiness) == len(ReadinessFacet)
    assert all(r.state is ReadinessFacetState.READY for r in projection.readiness)
    assert projection.alignment.state is ObjectiveAttributionState.ATTRIBUTED
    assert projection.alignment.finalized_events == 120
    assert projection.alignment.attributed_events == 120
    assert projection.alignment.unattributed_events == 0
    assert projection.alignment.coverage == 1.0
    assert len(projection.outcomes) == 5
    assert all(o.state is OutcomeEvidenceState.MEASURED for o in projection.outcomes)
    assert projection.guards.state is ControlAssuranceState.HEALTHY
    assert projection.guards.policy_escape_count == 0
    assert all(g.passed for g in projection.guards.guard_evaluations)


def test_simulate_action_promotions_qualifies_all_catalog_action_types() -> None:
    from fdai.core.measurement import simulate_action_promotions

    catalog = load_action_type_catalog(
        REPO_ROOT / "rule-catalog" / "action-types",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=None,
    )
    assert len(catalog) == 58
    eligible = tuple(item for item in catalog if item.promotion_gate.min_accuracy < 1.0)
    assert len(eligible) == 42
    clock = SimulatedTimeClock(datetime(2026, 10, 1, 0, 0, tzinfo=UTC))
    receipts = simulate_action_promotions(
        action_types=eligible,
        clock=clock,
        days=30,
        live_samples_per_day=4,
        benchmark_samples=20,
        fdai_revision="a" * 40,
        scenario_set_version="v2026.10",
    )
    assert len(receipts) == 42
    assert all(r.ready and r.gaps == () for r in receipts)


def test_guard_breach_and_rollback_spike_triggers_auto_demotion() -> None:
    from fdai.core.measurement import simulate_guard_breach_auto_demotion

    clock = SimulatedTimeClock(datetime(2026, 10, 1, 0, 0, tzinfo=UTC))
    sim = simulate_guard_breach_auto_demotion(clock=clock)

    assert sim.demoted_to_shadow is True
    assert sim.regression_decision.outcome.value == "guard_breach"
    assert len(sim.regression_decision.reasons) == 3
    assert sim.failed_settlement.rollback_request is not None
    assert sim.failed_settlement.recovery_observed is True
    assert sim.failed_settlement.terminal is True
    assert sim.failed_settlement.realized_savings == Decimal("0")


def test_invoice_allocated_settlements_and_t1_pattern_holdout() -> None:
    from fdai.core.measurement import (
        simulate_invoice_allocated_settlements,
        simulate_t1_pattern_growth_holdout,
    )
    from fdai.shared.providers.cost_governance_decision import CostSavingsEvidenceClass

    clock = SimulatedTimeClock(datetime(2026, 10, 1, 0, 0, tzinfo=UTC))
    invoice_settlements = simulate_invoice_allocated_settlements(clock=clock, billing_cycle_days=35)
    assert len(invoice_settlements) == 6
    for settlement in invoice_settlements:
        assert settlement.terminal is True
        assert (
            settlement.realized_savings_evidence_class is CostSavingsEvidenceClass.INVOICE_ALLOCATED
        )
        assert settlement.realized_savings is not None and settlement.realized_savings > 0

    holdout_sim = simulate_t1_pattern_growth_holdout(clock=clock)
    assert holdout_sim.accepted_intake_count == 15
    assert holdout_sim.rejected_intake_count == 1
    assert holdout_sim.holdout_decision.outcome.value == "pass"
    assert holdout_sim.holdout_decision.sample_size == 25
    assert holdout_sim.holdout_decision.observed_fp_rate == 0.04


async def test_multi_vertical_outcome_assurance_rollup_zstd_archive_and_seeding() -> None:
    from fdai.core.measurement import (
        OutcomeVertical,
        build_multi_vertical_outcome_projections,
        seed_simulated_enterprise_state_store,
        simulate_rollup_and_zstd_archive_lifecycle,
    )
    from fdai.core.ontology_platform.zstd_codec import (
        ZSTD_PROFILE_DICT,
        ZSTD_PROFILE_FRAME,
        decompress_canonical_json,
    )
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    policy = load_cohort_claim_policy(REPO_ROOT / "config" / "sre-cohort-claim-policy.json")
    catalog = load_action_type_catalog(
        REPO_ROOT / "rule-catalog" / "action-types",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=None,
    )
    selected = tuple(catalog[:6])
    clock = SimulatedTimeClock(datetime(2026, 10, 1, 0, 0, tzinfo=UTC))
    cohort = run_simulated_multi_day_cohort(
        policy=policy,
        action_types=selected,
        days=30,
        samples_per_day=4,
    )
    multi = build_multi_vertical_outcome_projections(
        clock=clock,
        days=30,
        samples_per_day=4,
        action_types=selected,
        baseline_facts=cohort.baseline_facts,
        treatment_facts=cohort.treatment_facts,
    )
    assert set(multi) == {
        OutcomeVertical.RESILIENCE,
        OutcomeVertical.CHANGE_SAFETY,
        OutcomeVertical.COST_GOVERNANCE,
    }
    for proj in multi.values():
        assert proj.alignment.state is ObjectiveAttributionState.ATTRIBUTED
        assert proj.alignment.coverage == 1.0
        assert proj.guards.state is ControlAssuranceState.HEALTHY

    release_digest = "sha256:" + "a" * 64
    zstd_res = simulate_rollup_and_zstd_archive_lifecycle(
        clock=clock,
        days=30,
        ontology_release_digest=release_digest,
    )
    assert zstd_res.rollup.complete is True
    assert zstd_res.rollup.observation_count == 30
    assert zstd_res.frame_archive_bundle.verification_receipt.verified is True
    assert zstd_res.dict_archive_bundle.verification_receipt.verified is True
    assert zstd_res.frame_archive_bundle.artifact.profile == ZSTD_PROFILE_FRAME
    assert zstd_res.dict_archive_bundle.artifact.profile == ZSTD_PROFILE_DICT
    assert zstd_res.frame_archive_bundle.artifact.space_savings_pct > 85.0
    assert (
        zstd_res.small_record_with_dict.compressed_byte_length
        < zstd_res.small_record_no_dict.compressed_byte_length
    )
    roundtrip = decompress_canonical_json(
        zstd_res.dict_archive_bundle.artifact,
        dictionary=zstd_res.dictionary,
    )
    assert roundtrip["rollup_digest"] == zstd_res.rollup.digest

    state_store = InMemoryStateStore()
    written_keys = await seed_simulated_enterprise_state_store(
        state_store,
        projections=multi,
        archive_result=zstd_res,
    )
    assert len(written_keys) == 4
