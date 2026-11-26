"""Exhaustive 55-round verification of 100% causal inference, forecasting, and impact coverage."""

from __future__ import annotations

import pytest
from fdai.core.detection.forecast import ForecastDetectorDecision
from fdai.core.rca.hypothesis import CausalHypothesisStatus
from fdai.delivery.azure.arg_catalog_relationships import (
    load_arg_relationship_mapping_catalog,
)
from fdai.delivery.azure.arg_public_catalog import load_arg_public_catalog
from fdai.delivery.azure.catalog_causal_inference import (
    ARG_CAUSE_DOMAIN_BY_TABLE,
    ARG_CHANGE_BEARING_TABLES,
    MONITOR_CAUSE_DOMAIN_BY_CATEGORY,
)
from fdai.delivery.azure.catalog_causal_prediction_engine import (
    CatalogCausalPredictionOrchestrator,
    load_causal_prediction_scenario_catalog,
)
from fdai.delivery.azure.catalog_forecast_prediction import (
    build_amba_pre_breach_forecasters,
    build_catalog_forecast_target_specs,
    build_catalog_linear_forecasters,
    build_catalog_slo_specs,
)
from fdai.delivery.azure.catalog_impact_and_resilience import (
    build_catalog_objective_bounds,
)
from fdai.delivery.azure.catalog_read_investigation import CATALOG_READ_TOOL_SPECS
from fdai.delivery.azure.catalog_telemetry_mechanisms import (
    load_causal_mechanism_and_probe_catalog,
)
from fdai.delivery.azure.monitor_log_catalog import load_monitor_log_catalog
from fdai.delivery.azure.resource_type_recipes import load_resource_type_recipe_catalog
from fdai.shared.contracts.models import CausalEvidenceGrade

_ROUND_CODES = tuple(f"D{i:03d}" for i in range(1, 56))


@pytest.mark.parametrize("round_code", _ROUND_CODES)
def test_each_of_55_rounds_executes_causal_inference_forecasting_and_impact_end_to_end(
    round_code: str,
) -> None:
    scenario_cat = load_causal_prediction_scenario_catalog()
    orchestrator = CatalogCausalPredictionOrchestrator()
    spec = scenario_cat.get_by_round(round_code)
    report = orchestrator.execute_scenario(spec)

    assert report.execution_authority is False
    assert len(report.compiled_arg_queries) == len(spec.arg_tables)
    assert len(report.compiled_monitor_queries) == len(spec.monitor_log_tables)
    assert len(report.dispatched_tools) == len(spec.read_tool_ids)

    # 1. Causal Inference verification
    causal = report.causal_result
    assert causal.execution_authority is False
    assert causal.causal_chain is not None
    assert len(causal.causal_chain.hops) == 2
    assert 0.35 <= causal.causal_chain.confidence <= 0.85
    assert causal.temporal_claim is not None
    assert causal.temporal_claim.lag_seconds == 60
    assert causal.temporal_claim.evidence_grade in {
        CausalEvidenceGrade.PREDICTIVE_PRECEDENCE,
        CausalEvidenceGrade.ASSOCIATION,
    }
    assert causal.hypothesis_record.status is CausalHypothesisStatus.SUPPORTED
    assert len(causal.citations) == 2

    # 2. Proactive Forecasting, AMBA Pre-Breach & Multi-Window SLO Burn-Rate verification
    forecast = report.forecast_result
    assert forecast.execution_authority is False
    assert forecast.evaluation.decision is ForecastDetectorDecision.PREDICTED_BREACH
    assert forecast.finding is not None
    assert 0 < forecast.finding.lead_time_seconds <= 1800.0
    assert forecast.band is not None
    assert len(forecast.slo_breaches) == 2

    # 3. Blast-Radius, ObjectiveBound & DR RTO/RPO verification
    impact = report.impact_result
    assert impact.execution_authority is False
    assert impact.total_impacted_count >= 3
    assert len(impact.objective_bounds) == 2
    assert 0.0 < impact.cascading_failure_probability < 1.0
    assert len(impact.resilience_prediction.recovery_arg_tables) == 5
    assert len(impact.drift_security_tables) == 5

    # 4. Prioritized Recommendations verification
    assert len(report.recommendations) == 2
    assert report.recommendations[0].priority.value == "p1"


def test_55_rounds_union_achieves_exact_100_percent_utilization_of_all_catalogs() -> None:
    scenario_cat = load_causal_prediction_scenario_catalog()
    assert scenario_cat.total_rounds == 55
    assert scenario_cat.total_families == 11
    assert len(scenario_cat.scenarios) == 55

    arg_cat = load_arg_public_catalog()
    mon_cat = load_monitor_log_catalog()
    rec_cat = load_resource_type_recipe_catalog()
    mech_cat = load_causal_mechanism_and_probe_catalog()
    rel_cat = load_arg_relationship_mapping_catalog()

    # Check domain mappings
    assert set(ARG_CAUSE_DOMAIN_BY_TABLE.keys()) == set(arg_cat.tables.keys())
    assert len(ARG_CHANGE_BEARING_TABLES) == 12
    assert set(MONITOR_CAUSE_DOMAIN_BY_CATEGORY.keys()) == set(mon_cat.categories.keys())

    # Check forecasting & impact primitive builders
    assert len(build_catalog_forecast_target_specs()) == 312
    assert len(build_catalog_linear_forecasters()) == 312
    assert len(build_amba_pre_breach_forecasters()) == 350
    assert len(build_catalog_slo_specs()) == 156
    assert len(build_catalog_objective_bounds()) == 156

    used_arg_tables: set[str] = set()
    used_arg_rtypes = 0
    used_arm_types = 0
    used_rels: set[str] = set()
    used_mon_cats: set[str] = set()
    used_mon_tables: set[str] = set()
    used_rts: set[str] = set()
    used_metrics: set[str] = set()
    used_kqls: set[str] = set()
    used_ambas: set[str] = set()
    used_mechs: set[str] = set()
    used_probes: set[str] = set()
    used_tools: set[str] = set()

    for spec in scenario_cat.scenarios.values():
        used_arg_tables.update(spec.arg_tables)
        used_arg_rtypes += spec.arg_resource_types_count
        used_arm_types += spec.arm_schema_types_count
        used_rels.update(spec.relationship_mapping_ids)
        used_mon_cats.update(spec.monitor_categories)
        used_mon_tables.update(spec.monitor_log_tables)
        used_rts.update(spec.canonical_resource_types)
        used_metrics.update(spec.platform_metric_ids)
        used_kqls.update(spec.kql_recipe_ids)
        used_ambas.update(spec.amba_alert_ids)
        used_mechs.update(spec.causal_mechanisms)
        used_probes.update(spec.diagnostic_probe_ids)
        used_tools.update(spec.read_tool_ids)

    assert used_arg_tables == set(arg_cat.tables.keys())  # 50 / 50 (100%)
    assert used_arg_rtypes == 1908  # 1,908 / 1,908 (100%)
    assert used_arm_types == 3405  # 3,405 / 3,405 (100%)
    assert used_rels == set(rel_cat.mappings.keys())  # 420 / 420 (100%)
    assert used_mon_cats == set(mon_cat.categories.keys())  # 12 / 12 (100%)
    assert used_mon_tables == set(mon_cat.tables.keys())  # 867 / 867 (100%)
    assert used_rts == set(rec_cat.profiles.keys())  # 156 / 156 (100%)
    assert used_metrics == set(rec_cat.platform_metrics.keys())  # 312 / 312 (100%)
    assert used_kqls == set(rec_cat.kql_recipes.keys())  # 156 / 156 (100%)
    assert used_ambas == set(rec_cat.amba_alerts.keys())  # 350 / 350 (100%)
    assert len(used_mechs) == mech_cat.total_mechanisms == 24  # 24 / 24 (100%)
    assert used_probes == set(mech_cat.probes.keys())  # 50 / 50 (100%)
    assert len(used_tools) == len(CATALOG_READ_TOOL_SPECS) == 20  # 20 / 20 (100%)
