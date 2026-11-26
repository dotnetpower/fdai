"""Tests for Area C (Items 12-16): Business semantics and FinOps value modeling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fdai.core.ontology_platform.decision_evidence_readers import (
    OntologyCostOfDelayEvidenceReader,
)
from fdai.core.ontology_platform.decision_functions import assess_cost_of_delay
from fdai.core.ontology_platform.finops_value_modeling import (
    BudgetBurnEvidence,
    CostObservationOntologyProjector,
    SizingCandidateInput,
    UnitEconomicsWindow,
    assess_budget_burn_risk,
    evaluate_unit_economics,
    filter_safe_sizing_recommendations,
    score_business_service_criticality,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.cost_governance import CostObservation as ProviderCostObservation
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

REPO_ROOT = Path(__file__).resolve().parents[5]
NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


async def test_item12_cost_observation_projector_feeds_cost_of_delay_reader() -> None:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    store = InMemoryOntologyInstanceStore(
        object_types=catalog.object_types, link_types=catalog.link_types
    )
    await store.upsert_object(
        OntologyObjectRecord(
            id="res-vm-1", object_type="Resource", properties={"id": "res-vm-1", "type": "compute"}
        )
    )
    projector = CostObservationOntologyProjector(store, metric="cost")
    provider_obs = ProviderCostObservation(
        observation_id="cost-obs-1",
        package_id="pkg-cost",
        scope_id="scope-1",
        service_id="compute",
        amount=Decimal("240.00"),
        currency="USD",
        event_start_at=NOW - timedelta(hours=25),
        event_end_at=NOW - timedelta(hours=1),
        observed_at=NOW - timedelta(minutes=15),
        recorded_at=NOW - timedelta(minutes=10),
        source_authority="azure-cost-management",
        source_uri="https://management.azure.com/cost",
        completeness=Decimal("1"),
        ontology_release_id="rel-1",
        ontology_release_digest="sha256:" + "a" * 64,
        evidence_digest="sha256:" + "b" * 64,
        retention_until=NOW + timedelta(days=90),
    )
    await projector.project_observation(provider_obs, target_resource_ref="res-vm-1")

    reader = OntologyCostOfDelayEvidenceReader(
        store, metric="cost", max_observation_age=timedelta(hours=6), clock=lambda: NOW
    )
    evidence = await reader.read(target_ref="res-vm-1")
    assert evidence is not None
    assert evidence.hourly_cost_amount == Decimal("10")
    assert evidence.currency == "USD"
    signal = assess_cost_of_delay(evidence, target_ref="res-vm-1", delay_hours=6)
    assert signal["total_amount"] == "60"


def test_item13_budget_burn_risk_forecasts_overrun_and_gates() -> None:
    within = assess_budget_burn_risk(
        BudgetBurnEvidence(
            budget_limit_amount=Decimal("1000"),
            spent_to_date_amount=Decimal("400"),
            daily_burn_rate=Decimal("20"),
            remaining_days=15,
            currency="USD",
            observed_at=NOW,
        ),
        target_ref="svc-1",
        max_projected_utilization_ratio=1.0,
    )
    assert within["projected_total_amount"] == "700"
    assert within["projected_utilization_ratio"] == 0.7
    assert within["tier"] == "low"
    assert within["gate_satisfied"] is True

    overrun = assess_budget_burn_risk(
        BudgetBurnEvidence(
            budget_limit_amount=Decimal("1000"),
            spent_to_date_amount=Decimal("800"),
            daily_burn_rate=Decimal("30"),
            remaining_days=10,
            currency="USD",
            observed_at=NOW,
        ),
        target_ref="svc-1",
        max_projected_utilization_ratio=1.0,
    )
    assert overrun["projected_total_amount"] == "1100"
    assert overrun["tier"] == "high"
    assert overrun["gate_satisfied"] is False


def test_item14_multi_objective_service_criticality_scoring() -> None:
    elevated = score_business_service_criticality(
        service_ref="svc-payments",
        base_criticality="medium",
        availability_target_pct=99.99,
        rto_target_minutes=10,
        has_cost_objective=True,
    )
    assert elevated.composite_weight == 2 + 4 + 4 + 1
    assert elevated.effective_tier == "critical"


def test_item15_filter_safe_sizing_recommendations() -> None:
    c1 = SizingCandidateInput(
        recommendation_id="rec-safe",
        target_resource_ref="vm-1",
        estimated_monthly_savings=Decimal("320"),
        currency="USD",
        confidence=0.92,
        in_change_window=True,
        slo_headroom_ok=True,
        blast_radius_tier="low",
    )
    c2 = SizingCandidateInput(
        recommendation_id="rec-unsafe-slo",
        target_resource_ref="vm-2",
        estimated_monthly_savings=Decimal("900"),
        currency="USD",
        confidence=0.95,
        in_change_window=True,
        slo_headroom_ok=False,
        blast_radius_tier="high",
    )
    report = filter_safe_sizing_recommendations((c1, c2))
    assert [c.recommendation_id for c in report.admitted] == ["rec-safe"]
    assert report.total_admitted_monthly_savings == Decimal("320")
    assert set(report.rejected_reasons["rec-unsafe-slo"]) == {
        "insufficient_slo_headroom",
        "blast_radius_exceeds_ceiling",
    }


def test_item16_unit_economics_blocks_false_savings_from_throughput_drop_or_slo_breach() -> None:
    base = UnitEconomicsWindow(total_cost_amount=Decimal("1000"), throughput_units=Decimal("10000"))
    genuine = UnitEconomicsWindow(
        total_cost_amount=Decimal("700"), throughput_units=Decimal("10000")
    )
    verdict = evaluate_unit_economics(baseline=base, treatment=genuine)
    assert verdict.valid_efficiency_gain is True
    assert verdict.unit_cost_reduction_ratio == 0.3

    collapsed_traffic = UnitEconomicsWindow(
        total_cost_amount=Decimal("500"), throughput_units=Decimal("4000")
    )
    bad_verdict = evaluate_unit_economics(baseline=base, treatment=collapsed_traffic)
    assert bad_verdict.valid_efficiency_gain is False
    assert bad_verdict.reason_code == "blocked_by_throughput_drop"
