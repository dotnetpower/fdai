"""Load the 156-resource-type Azure Monitor metric, KQL, and 350-AMBA alert recipe catalogs.

Provides 100% telemetry recipe coverage across all 156 canonical ResourceTypes in
``rule-catalog/vocabulary/resource-types.yaml`` (312 platform metric recipes, 156
Log Analytics KQL recipes, 312 semantic metric definitions, and 350 AMBA baseline
alert rules). Read-only metadata only; never grants execution or mutation authority.
"""

from __future__ import annotations

import functools
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from fdai.delivery.azure.demo_queries import extended_monitor_log_metric_queries
from fdai.delivery.azure.metric_logs import MetricKqlTemplate
from fdai.delivery.azure.metrics_api import MetricsApiTemplate
from fdai.delivery.azure.metrics_api_queries import azure_extended_platform_metrics_api_queries
from fdai.delivery.repo_assets import repo_asset_root

_RECIPES_REL_PATH: Final[Path] = Path(
    "rule-catalog/collected/azure-monitor/resource-type-recipes.json"
)
_AMBA_REL_PATH: Final[Path] = Path("rule-catalog/collected/azure-monitor/amba-alert-recipes.json")
_ALLOWED_AGGREGATIONS: Final[frozenset[str]] = frozenset(
    {"Average", "Maximum", "Minimum", "Total", "Count"}
)
_ALLOWED_COMPARISONS: Final[frozenset[str]] = frozenset({"gte", "lte"})
_ALLOWED_SEVERITIES: Final[frozenset[str]] = frozenset({"low", "medium", "high", "critical"})


@dataclass(frozen=True, slots=True)
class PlatformMetricRecipe:
    """One declarative Azure Monitor platform metric recipe for a canonical ResourceType."""

    metric_id: str
    azure_metric_name: str
    metric_namespace: str
    aggregation: str
    unit: str
    comparison: str
    threshold: float
    severity: str
    signal: str
    observation: str

    def __post_init__(self) -> None:
        if (
            not self.metric_id.strip()
            or not self.azure_metric_name.strip()
            or not self.metric_namespace.strip()
            or not self.unit.strip()
            or not self.signal.strip()
            or not self.observation.strip()
        ):
            raise ValueError("PlatformMetricRecipe text fields MUST be non-empty")
        if self.aggregation not in _ALLOWED_AGGREGATIONS:
            raise ValueError(f"Unsupported aggregation: {self.aggregation!r}")
        if self.comparison not in _ALLOWED_COMPARISONS:
            raise ValueError(f"Unsupported comparison: {self.comparison!r}")
        if self.severity not in _ALLOWED_SEVERITIES:
            raise ValueError(f"Unsupported severity: {self.severity!r}")
        if type(self.threshold) is bool or not math.isfinite(self.threshold):
            raise ValueError("PlatformMetricRecipe.threshold MUST be a finite number")

    def to_metrics_api_template(self) -> MetricsApiTemplate:
        parts = [p for p in self.metric_namespace.split("/") if p]
        clean_kind = re.sub(r"[^A-Za-z0-9]", "", parts[1]) if len(parts) >= 2 else ""
        top_level_rt = (
            f"{parts[0]}/{clean_kind}"
            if len(parts) >= 2 and clean_kind and clean_kind[0].isalpha()
            else None
        )
        return MetricsApiTemplate(
            azure_metric_name=self.azure_metric_name,
            aggregation=self.aggregation,
            resource_type=top_level_rt,
        )


@dataclass(frozen=True, slots=True)
class KqlTelemetryRecipe:
    """One declarative Log Analytics KQL recipe for a canonical ResourceType."""

    kql_recipe_id: str
    log_table: str
    kql: str
    value_column: str
    timestamp_column: str
    label_columns: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not self.kql_recipe_id.strip()
            or not self.log_table.strip()
            or not self.kql.strip()
            or not self.value_column.strip()
            or not self.timestamp_column.strip()
            or not self.label_columns
        ):
            raise ValueError("KqlTelemetryRecipe fields MUST be non-empty")

    def to_kql_template(self) -> MetricKqlTemplate:
        return MetricKqlTemplate(
            kql=self.kql,
            value_column=self.value_column,
            timestamp_column=self.timestamp_column,
            label_columns=self.label_columns,
        )


@dataclass(frozen=True, slots=True)
class ResourceTypeRecipeProfile:
    """Complete platform-metric and KQL telemetry profile for one canonical ResourceType."""

    resource_type: str
    category: str
    azure_arm_type: str
    platform_metrics: tuple[PlatformMetricRecipe, ...]
    kql_recipe: KqlTelemetryRecipe

    def __post_init__(self) -> None:
        if (
            not self.resource_type.strip()
            or not self.category.strip()
            or not self.azure_arm_type.strip()
            or not self.platform_metrics
        ):
            raise ValueError("ResourceTypeRecipeProfile fields MUST be non-empty")


@dataclass(frozen=True, slots=True)
class AmbaAlertRecipe:
    """One Azure Monitor Baseline Alerts (AMBA) threshold alert rule definition."""

    alert_id: str
    resource_type: str
    azure_arm_type: str
    metric_id: str
    azure_metric_name: str
    aggregation: str
    operator: str
    threshold: float
    severity: int
    window_minutes: int
    evaluation_frequency_minutes: int
    description: str

    def __post_init__(self) -> None:
        if (
            not self.alert_id.strip()
            or not self.resource_type.strip()
            or not self.azure_arm_type.strip()
            or not self.metric_id.strip()
            or not self.azure_metric_name.strip()
            or not self.description.strip()
        ):
            raise ValueError("AmbaAlertRecipe text fields MUST be non-empty")
        if self.aggregation not in _ALLOWED_AGGREGATIONS:
            raise ValueError(f"Invalid AMBA aggregation: {self.aggregation!r}")
        if self.operator not in {
            "GreaterThan",
            "GreaterThanOrEqual",
            "LessThan",
            "LessThanOrEqual",
        }:
            raise ValueError(f"Invalid AMBA operator: {self.operator!r}")
        if type(self.threshold) is bool or not math.isfinite(self.threshold):
            raise ValueError("AmbaAlertRecipe.threshold MUST be finite")
        if type(self.severity) is not int or not 0 <= self.severity <= 4:
            raise ValueError("AmbaAlertRecipe.severity MUST be 0..4")
        if (
            type(self.window_minutes) is not int
            or type(self.evaluation_frequency_minutes) is not int
            or self.window_minutes < 1
            or self.evaluation_frequency_minutes < 1
        ):
            raise ValueError("AmbaAlertRecipe window and frequency MUST be positive integers")


@dataclass(frozen=True, slots=True)
class ResourceTypeRecipeCatalog:
    """In-memory catalog of 156 ResourceType profiles, 312 metrics, 156 KQL, and 350 AMBA rules."""

    profiles: Mapping[str, ResourceTypeRecipeProfile]
    platform_metrics: Mapping[str, PlatformMetricRecipe]
    kql_recipes: Mapping[str, KqlTelemetryRecipe]
    amba_alerts: Mapping[str, AmbaAlertRecipe]

    @property
    def total_resource_types(self) -> int:
        return len(self.profiles)

    @property
    def total_platform_metrics(self) -> int:
        return len(self.platform_metrics)

    @property
    def total_kql_recipes(self) -> int:
        return len(self.kql_recipes)

    @property
    def total_semantic_definitions(self) -> int:
        return len(self.platform_metrics)

    @property
    def total_amba_alerts(self) -> int:
        return len(self.amba_alerts)

    def get_profile(self, resource_type: str) -> ResourceTypeRecipeProfile:
        clean = resource_type.strip() if isinstance(resource_type, str) else ""
        if clean not in self.profiles:
            raise KeyError(f"Unknown canonical ResourceType: {resource_type!r}")
        return self.profiles[clean]


@functools.lru_cache(maxsize=2)
def load_resource_type_recipe_catalog(
    repo_root: Path | None = None,
) -> ResourceTypeRecipeCatalog:
    """Load and validate the 156-resource-type recipe catalog and 350 AMBA alert catalog."""
    root = repo_root or repo_asset_root()
    raw_recipes: dict[str, Any] = json.loads((root / _RECIPES_REL_PATH).read_text(encoding="utf-8"))
    raw_amba: dict[str, Any] = json.loads((root / _AMBA_REL_PATH).read_text(encoding="utf-8"))
    profiles: dict[str, ResourceTypeRecipeProfile] = {}
    platform_metrics: dict[str, PlatformMetricRecipe] = {}
    kql_recipes: dict[str, KqlTelemetryRecipe] = {}
    for entry in raw_recipes.get("recipes", ()):
        pm_list = tuple(
            PlatformMetricRecipe(
                metric_id=str(m["metric_id"]),
                azure_metric_name=str(m["azure_metric_name"]),
                metric_namespace=str(m["metric_namespace"]),
                aggregation=str(m["aggregation"]),
                unit=str(m["unit"]),
                comparison=str(m["comparison"]),
                threshold=float(m["threshold"]),
                severity=str(m["severity"]),
                signal=str(m["signal"]),
                observation=str(m["observation"]),
            )
            for m in entry["platform_metrics"]
        )
        kr_raw = entry["kql_recipe"]
        kr = KqlTelemetryRecipe(
            kql_recipe_id=str(kr_raw["kql_recipe_id"]),
            log_table=str(kr_raw["log_table"]),
            kql=str(kr_raw["kql"]),
            value_column=str(kr_raw["value_column"]),
            timestamp_column=str(kr_raw["timestamp_column"]),
            label_columns=tuple(str(c) for c in kr_raw["label_columns"]),
        )
        prof = ResourceTypeRecipeProfile(
            resource_type=str(entry["resource_type"]),
            category=str(entry["category"]),
            azure_arm_type=str(entry["azure_arm_type"]),
            platform_metrics=pm_list,
            kql_recipe=kr,
        )
        profiles[prof.resource_type] = prof
        for pm in pm_list:
            platform_metrics[pm.metric_id] = pm
        kql_recipes[kr.kql_recipe_id] = kr
    amba_dict: dict[str, AmbaAlertRecipe] = {}
    for item in raw_amba.get("alerts", ()):
        alert = AmbaAlertRecipe(
            alert_id=str(item["alert_id"]),
            resource_type=str(item["resource_type"]),
            azure_arm_type=str(item["azure_arm_type"]),
            metric_id=str(item["metric_id"]),
            azure_metric_name=str(item["azure_metric_name"]),
            aggregation=str(item["aggregation"]),
            operator=str(item["operator"]),
            threshold=float(item["threshold"]),
            severity=int(item["severity"]),
            window_minutes=int(item["window_minutes"]),
            evaluation_frequency_minutes=int(item["evaluation_frequency_minutes"]),
            description=str(item["description"]),
        )
        amba_dict[alert.alert_id] = alert
    return ResourceTypeRecipeCatalog(
        profiles=MappingProxyType(profiles),
        platform_metrics=MappingProxyType(platform_metrics),
        kql_recipes=MappingProxyType(kql_recipes),
        amba_alerts=MappingProxyType(amba_dict),
    )


def all_catalog_metrics_api_queries(
    repo_root: Path | None = None,
) -> Mapping[str, MetricsApiTemplate]:
    """Return all 312 catalog platform metric templates merged with existing templates."""
    cat = load_resource_type_recipe_catalog(repo_root)
    merged = {
        metric_id: recipe.to_metrics_api_template()
        for metric_id, recipe in cat.platform_metrics.items()
    }
    merged.update(azure_extended_platform_metrics_api_queries(include_defaults=True))
    return MappingProxyType(merged)


def all_catalog_kql_metric_queries(
    repo_root: Path | None = None,
) -> Mapping[str, MetricKqlTemplate]:
    """Return all 156 catalog KQL metric templates merged with existing KQL templates."""
    cat = load_resource_type_recipe_catalog(repo_root)
    merged = {recipe_id: recipe.to_kql_template() for recipe_id, recipe in cat.kql_recipes.items()}
    merged.update(extended_monitor_log_metric_queries(include_defaults=True))
    return MappingProxyType(merged)


__all__ = [
    "AmbaAlertRecipe",
    "KqlTelemetryRecipe",
    "PlatformMetricRecipe",
    "ResourceTypeRecipeCatalog",
    "ResourceTypeRecipeProfile",
    "all_catalog_kql_metric_queries",
    "all_catalog_metrics_api_queries",
    "load_resource_type_recipe_catalog",
]
