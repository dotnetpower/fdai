"""Unified 55-round causal inference, forecasting, and resilience orchestrator (D001-D055).

Executes all 55 end-to-end multi-hop scenarios across 11 operational scenario
families, uniting:
1. Direct ARG (50 tables) and Azure Monitor Log (867 tables) query compilation,
2. Multi-hop topological and temporal causal inference (:class:`CatalogCausalInferenceEngine`),
3. Linear breach forecasting, AMBA pre-breach ETA, and multi-window SLO burn-rate
   prediction (:class:`CatalogForecastPredictionEngine`),
4. Multi-hop blast-radius, ObjectiveBound impact envelopes, and DR RTO/RPO
   prediction (:class:`CatalogImpactAndResilienceEngine`), and
5. Prioritized P1..P3 recommendations with merged evidence citations and strict
   no-authority safety bounds (``execution_authority=False``).
"""

from __future__ import annotations

import functools
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from fdai.core.detection.series import MetricSample
from fdai.core.investigation.contract import AnalyzerFinding, Recommendation
from fdai.core.investigation.recommendations import build_recommendations
from fdai.delivery.azure.catalog_causal_inference import (
    CatalogCausalInferenceEngine,
    CatalogCausalInferenceResult,
    CatalogCausalObservation,
)
from fdai.delivery.azure.catalog_forecast_prediction import (
    CatalogForecastPredictionEngine,
    CatalogForecastPredictionResult,
)
from fdai.delivery.azure.catalog_impact_and_resilience import (
    BlastRadiusSimulationResult,
    CatalogImpactAndResilienceEngine,
)
from fdai.delivery.azure.catalog_read_investigation import (
    CatalogReadInvestigationDispatcher,
    CatalogReadToolId,
)
from fdai.delivery.azure.catalog_telemetry_mechanisms import CatalogTelemetryMechanism
from fdai.delivery.azure.resource_type_recipes import load_resource_type_recipe_catalog
from fdai.delivery.repo_assets import repo_asset_root
from fdai.shared.contracts.models import Severity

_SCENARIOS_REL_PATH: Final[Path] = Path(
    "rule-catalog/collected/azure-scenarios/causal-prediction-scenarios.json"
)


@dataclass(frozen=True, slots=True)
class CausalPredictionScenarioSpec:
    """Declarative specification for one of the 55 multi-hop causal & prediction scenarios."""

    scenario_id: str
    round_code: str
    round_number: int
    family_id: str
    family_title: str
    root_cause_resource_type: str
    intermediate_resource_type: str
    failure_resource_type: str
    primary_metric_id: str
    cause_metric_id: str
    primary_amba_alert_id: str
    arg_tables: tuple[str, ...]
    arg_resource_types_count: int
    arm_schema_types_count: int
    relationship_mapping_ids: tuple[str, ...]
    monitor_categories: tuple[str, ...]
    monitor_log_tables: tuple[str, ...]
    canonical_resource_types: tuple[str, ...]
    platform_metric_ids: tuple[str, ...]
    kql_recipe_ids: tuple[str, ...]
    amba_alert_ids: tuple[str, ...]
    causal_mechanisms: tuple[str, ...]
    diagnostic_probe_ids: tuple[str, ...]
    read_tool_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.scenario_id.strip() or not self.round_code.strip():
            raise ValueError("CausalPredictionScenarioSpec scenario_id and round_code required")
        if type(self.round_number) is not int or not 1 <= self.round_number <= 100:
            raise ValueError("CausalPredictionScenarioSpec.round_number MUST be in 1..100")


@dataclass(frozen=True, slots=True)
class CausalPredictionScenarioCatalog:
    """In-memory catalog of all 55 end-to-end causal inference and prediction scenarios."""

    schema_version: str
    total_rounds: int
    total_families: int
    scenarios: Mapping[str, CausalPredictionScenarioSpec]
    by_round_code: Mapping[str, CausalPredictionScenarioSpec]

    def get_by_round(self, round_code: str) -> CausalPredictionScenarioSpec:
        clean = round_code.strip().upper() if isinstance(round_code, str) else ""
        if clean not in self.by_round_code:
            raise KeyError(f"Unknown round_code: {round_code!r}")
        return self.by_round_code[clean]


@functools.lru_cache(maxsize=2)
def load_causal_prediction_scenario_catalog(
    repo_root: Path | None = None,
) -> CausalPredictionScenarioCatalog:
    """Load and validate all 55 multi-hop causal inference and prediction scenarios."""
    root = repo_root or repo_asset_root()
    raw: dict[str, Any] = json.loads((root / _SCENARIOS_REL_PATH).read_text(encoding="utf-8"))
    by_id: dict[str, CausalPredictionScenarioSpec] = {}
    by_round: dict[str, CausalPredictionScenarioSpec] = {}
    for item in raw.get("scenarios", ()):
        spec = CausalPredictionScenarioSpec(
            scenario_id=str(item["scenario_id"]),
            round_code=str(item["round_code"]),
            round_number=int(item["round_number"]),
            family_id=str(item["family_id"]),
            family_title=str(item["family_title"]),
            root_cause_resource_type=str(item["root_cause_resource_type"]),
            intermediate_resource_type=str(item["intermediate_resource_type"]),
            failure_resource_type=str(item["failure_resource_type"]),
            primary_metric_id=str(item["primary_metric_id"]),
            cause_metric_id=str(item["cause_metric_id"]),
            primary_amba_alert_id=str(item["primary_amba_alert_id"]),
            arg_tables=tuple(str(x) for x in item["arg_tables"]),
            arg_resource_types_count=int(item["arg_resource_types_count"]),
            arm_schema_types_count=int(item["arm_schema_types_count"]),
            relationship_mapping_ids=tuple(str(x) for x in item["relationship_mapping_ids"]),
            monitor_categories=tuple(str(x) for x in item["monitor_categories"]),
            monitor_log_tables=tuple(str(x) for x in item["monitor_log_tables"]),
            canonical_resource_types=tuple(str(x) for x in item["canonical_resource_types"]),
            platform_metric_ids=tuple(str(x) for x in item["platform_metric_ids"]),
            kql_recipe_ids=tuple(str(x) for x in item["kql_recipe_ids"]),
            amba_alert_ids=tuple(str(x) for x in item["amba_alert_ids"]),
            causal_mechanisms=tuple(str(x) for x in item["causal_mechanisms"]),
            diagnostic_probe_ids=tuple(str(x) for x in item["diagnostic_probe_ids"]),
            read_tool_ids=tuple(str(x) for x in item["read_tool_ids"]),
        )
        by_id[spec.scenario_id] = spec
        by_round[spec.round_code] = spec
    return CausalPredictionScenarioCatalog(
        schema_version=str(raw["schema_version"]),
        total_rounds=int(raw["total_rounds"]),
        total_families=int(raw["total_families"]),
        scenarios=MappingProxyType(by_id),
        by_round_code=MappingProxyType(by_round),
    )


@dataclass(frozen=True, slots=True)
class ScenarioExecutionReport:
    """Complete execution outcome for one of the 55 causal inference & prediction scenarios."""

    scenario: CausalPredictionScenarioSpec
    compiled_arg_queries: tuple[str, ...]
    compiled_monitor_queries: tuple[str, ...]
    dispatched_tools: tuple[str, ...]
    causal_result: CatalogCausalInferenceResult
    forecast_result: CatalogForecastPredictionResult
    impact_result: BlastRadiusSimulationResult
    recommendations: tuple[Recommendation, ...]
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if type(self.execution_authority) is not bool or self.execution_authority:
            raise ValueError("ScenarioExecutionReport MUST have execution_authority=False")


class CatalogCausalPredictionOrchestrator:
    """Execute end-to-end causal inference, forecasting, and impact simulation scenarios."""

    def __init__(self, *, repo_root: Path | None = None) -> None:
        self._repo_root = repo_root
        self._scenarios = load_causal_prediction_scenario_catalog(repo_root)
        self._recipes = load_resource_type_recipe_catalog(repo_root)
        self._dispatcher = CatalogReadInvestigationDispatcher(repo_root=repo_root)
        self._causal = CatalogCausalInferenceEngine(repo_root=repo_root)
        self._forecast = CatalogForecastPredictionEngine(repo_root=repo_root)
        self._impact = CatalogImpactAndResilienceEngine(repo_root=repo_root)

    def execute_scenario(
        self,
        spec: CausalPredictionScenarioSpec,
        *,
        base_time: datetime | None = None,
    ) -> ScenarioExecutionReport:
        """Run one complete scenario through query compilation, RCA, forecasting, and impact."""
        t0 = (base_time or datetime(2026, 11, 1, 5, 0, tzinfo=UTC)).astimezone(UTC)

        arg_queries = tuple(
            self._dispatcher.compile_direct_query(CatalogReadToolId.QUERY_ARG_TABLE, target=tbl)[
                "kql"
            ]
            for tbl in spec.arg_tables
        )
        mon_queries = tuple(
            self._dispatcher.compile_direct_query(
                CatalogReadToolId.QUERY_MONITOR_LOG_TABLE, target=tbl
            )["kql"]
            for tbl in spec.monitor_log_tables
        )
        dispatched = tuple(
            self._dispatcher.compile_direct_query(CatalogReadToolId(tid))["tool_id"]
            for tid in spec.read_tool_ids
        )

        root_ref = f"res:{spec.round_code.lower()}:root:{spec.root_cause_resource_type}"
        mid_ref = f"res:{spec.round_code.lower()}:mid:{spec.intermediate_resource_type}"
        fail_ref = f"res:{spec.round_code.lower()}:fail:{spec.failure_resource_type}"

        mech_enum = CatalogTelemetryMechanism(spec.causal_mechanisms[0])
        probe_id = spec.diagnostic_probe_ids[0]
        arg_tbl = spec.arg_tables[0]
        mon_tbl = spec.monitor_log_tables[0]

        root_obs = CatalogCausalObservation(
            event_id=f"evt:{spec.round_code.lower()}:root-change",
            occurred_at=t0 - timedelta(minutes=12),
            resource_ref=root_ref,
            resource_type=spec.root_cause_resource_type,
            arg_table=arg_tbl,
            monitor_table=mon_tbl,
            mechanism=mech_enum,
            probe_id=probe_id,
            is_change=True,
            change_kind="config_or_deploy",
        )
        mid_obs = CatalogCausalObservation(
            event_id=f"evt:{spec.round_code.lower()}:mid-symptom",
            occurred_at=t0 - timedelta(minutes=6),
            resource_ref=mid_ref,
            resource_type=spec.intermediate_resource_type,
            arg_table=arg_tbl,
            monitor_table=mon_tbl,
            mechanism=mech_enum,
            probe_id=probe_id,
            is_change=False,
        )
        fail_obs = CatalogCausalObservation(
            event_id=f"evt:{spec.round_code.lower()}:failure",
            occurred_at=t0,
            resource_ref=fail_ref,
            resource_type=spec.failure_resource_type,
            arg_table=arg_tbl,
            monitor_table=mon_tbl,
            mechanism=mech_enum,
            probe_id=probe_id,
            is_change=False,
        )

        # Build lagged time-series where cause leads effect by 60 seconds (8 samples)
        cause_vals = (10.0, 12.0, 25.0, 45.0, 70.0, 88.0, 95.0, 98.0)
        effect_vals = (10.0, 10.0, 12.0, 25.0, 45.0, 70.0, 88.0, 95.0)
        cause_series = tuple(
            MetricSample(timestamp=t0 - timedelta(minutes=8 - idx), value=val)
            for idx, val in enumerate(cause_vals)
        )
        effect_series = tuple(
            MetricSample(timestamp=t0 - timedelta(minutes=8 - idx), value=val)
            for idx, val in enumerate(effect_vals)
        )

        depends_on = {
            fail_ref: frozenset({mid_ref}),
            mid_ref: frozenset({root_ref}),
        }
        causal_result = self._causal.infer_causality(
            incident_id=f"inc:{spec.round_code.lower()}",
            failure=fail_obs,
            antecedents=(root_obs, mid_obs),
            depends_on=depends_on,
            relationship_mapping_ids=spec.relationship_mapping_ids,
            cause_series=cause_series,
            effect_series=effect_series,
            cause_metric_id=spec.cause_metric_id,
            effect_metric_id=spec.primary_metric_id,
            cutoff=t0,
        )

        pm_recipe = self._recipes.platform_metrics[spec.primary_metric_id]
        thresh = pm_recipe.threshold
        if pm_recipe.comparison == "gte":
            # Rising toward threshold within 1800s horizon (currently below threshold)
            start_v = thresh * 0.50
            step_v = (thresh * 0.35) / 5.0
            forecast_samples = tuple(
                MetricSample(
                    timestamp=t0 - timedelta(minutes=5 - idx),
                    value=start_v + step_v * idx,
                )
                for idx in range(6)
            )
        else:
            # Falling toward threshold within 1800s horizon (currently above threshold)
            start_v = thresh * 1.005 if thresh >= 90.0 else thresh * 1.50
            step_v = ((start_v - thresh) * 0.70) / 5.0
            forecast_samples = tuple(
                MetricSample(
                    timestamp=t0 - timedelta(minutes=5 - idx),
                    value=start_v - step_v * idx,
                )
                for idx in range(6)
            )

        forecast_result = self._forecast.predict(
            resource_ref=fail_ref,
            resource_type=spec.failure_resource_type,
            metric_id=spec.primary_metric_id,
            amba_alert_id=spec.primary_amba_alert_id,
            history=forecast_samples,
            short_good_events=950,
            short_total_events=1000,
            long_good_events=9500,
            long_total_events=10000,
        )

        downstream_adj = {
            root_ref: (mid_ref,),
            mid_ref: (
                fail_ref,
                *(
                    f"res:{spec.round_code.lower()}:leaf:{rt}"
                    for rt in spec.canonical_resource_types
                ),
            ),
        }
        impact_result = self._impact.simulate(
            root_resource_ref=root_ref,
            root_resource_type=spec.root_cause_resource_type,
            downstream_adjacency=downstream_adj,
            relationship_mapping_ids=spec.relationship_mapping_ids,
            chaos_probe_id=probe_id,
            estimated_recovery_minutes=25.0,
            estimated_data_loss_minutes=20.0,
        )

        findings = (
            AnalyzerFinding(
                resource_ref=root_ref,
                resource_kind=spec.root_cause_resource_type,
                signal=mech_enum.value,
                observation=(
                    f"Root change on {spec.root_cause_resource_type} "
                    f"propagated via {mech_enum.value}."
                ),
                severity=Severity.CRITICAL,
                occurred_at=t0 - timedelta(minutes=12),
                evidence_refs=(f"arg:{arg_tbl}", f"monitor:{mon_tbl}"),
            ),
            AnalyzerFinding(
                resource_ref=fail_ref,
                resource_kind=spec.failure_resource_type,
                signal=spec.primary_metric_id,
                observation=(
                    f"Proactive breach predicted on {spec.failure_resource_type} "
                    f"({spec.primary_metric_id})."
                ),
                severity=Severity.HIGH,
                occurred_at=t0,
                evidence_refs=(f"amba:{spec.primary_amba_alert_id}", f"probe:{probe_id}"),
            ),
        )
        recommendations = build_recommendations(findings)
        return ScenarioExecutionReport(
            scenario=spec,
            compiled_arg_queries=arg_queries,
            compiled_monitor_queries=mon_queries,
            dispatched_tools=dispatched,
            causal_result=causal_result,
            forecast_result=forecast_result,
            impact_result=impact_result,
            recommendations=recommendations,
        )


__all__ = [
    "CatalogCausalPredictionOrchestrator",
    "CausalPredictionScenarioCatalog",
    "CausalPredictionScenarioSpec",
    "ScenarioExecutionReport",
    "load_causal_prediction_scenario_catalog",
]
