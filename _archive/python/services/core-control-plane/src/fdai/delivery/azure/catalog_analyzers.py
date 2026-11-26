"""Catalog-driven ResourceAnalyzers covering 100% (156/156) of canonical ResourceTypes.

Constructs a deterministic :class:`~fdai.core.investigation.analyzer.ThresholdAnalyzer`
for every canonical ``ResourceType`` in ``rule-catalog/vocabulary/resource-types.yaml``
from its declarative metric recipes in ``resource-type-recipes.json``, without
mutating the demo-pinned ``ANALYZER_KIND_BY_RESOURCE_TYPE`` or ``default_analyzers()``.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Final

from fdai.core.investigation.analyzer import (
    Aggregation,
    Comparison,
    ResourceAnalyzer,
    Threshold,
    ThresholdAnalyzer,
)
from fdai.delivery.azure.resource_type_recipes import load_resource_type_recipe_catalog
from fdai.shared.contracts.models import Severity
from fdai.shared.providers.metric import MetricProvider

_AGG_MAP: Final[Mapping[str, Aggregation]] = {
    "Average": Aggregation.AVG,
    "Maximum": Aggregation.MAX,
    "Minimum": Aggregation.MIN,
    "Total": Aggregation.SUM,
    "Count": Aggregation.SUM,
}
_CMP_MAP: Final[Mapping[str, Comparison]] = {
    "gte": Comparison.GTE,
    "lte": Comparison.LTE,
}
_SEV_MAP: Final[Mapping[str, Severity]] = {
    "low": Severity.LOW,
    "medium": Severity.MEDIUM,
    "high": Severity.HIGH,
    "critical": Severity.CRITICAL,
}


@functools.lru_cache(maxsize=2)
def catalog_analyzer_kind_by_resource_type(
    repo_root: Path | None = None,
) -> Mapping[str, str]:
    """Return the complete 156-entry ``resource_type -> analyzer_kind`` mapping."""
    catalog = load_resource_type_recipe_catalog(repo_root)
    mapping: dict[str, str] = {}
    for rt in sorted(catalog.profiles):
        kind = "catalog." + rt.replace(".", "_").replace("-", "_")
        mapping[rt] = kind
    return MappingProxyType(mapping)


def build_catalog_resource_type_analyzers(
    provider: MetricProvider,
    *,
    wall_clock: Callable[[], datetime] | None = None,
    repo_root: Path | None = None,
) -> tuple[ResourceAnalyzer, ...]:
    """Instantiate deterministic ThresholdAnalyzers for all 156 canonical ResourceTypes."""
    catalog = load_resource_type_recipe_catalog(repo_root)
    analyzers: list[ResourceAnalyzer] = []
    for rt, profile in sorted(catalog.profiles.items()):
        kind = "catalog." + rt.replace(".", "_").replace("-", "_")
        thresholds: list[Threshold] = []
        for pm in profile.platform_metrics:
            thresholds.append(
                Threshold(
                    metric=pm.metric_id,
                    compare=_CMP_MAP[pm.comparison],
                    bound=pm.threshold,
                    severity=_SEV_MAP[pm.severity],
                    signal=pm.signal,
                    observation=pm.observation,
                    aggregation=_AGG_MAP[pm.aggregation],
                )
            )
        analyzers.append(
            ThresholdAnalyzer(
                resource_kind=kind,
                provider=provider,
                thresholds=tuple(thresholds),
                wall_clock=wall_clock,
            )
        )
    return tuple(analyzers)


__all__ = [
    "build_catalog_resource_type_analyzers",
    "catalog_analyzer_kind_by_resource_type",
]
