"""Read-only semantic metric handlers and optional independent competitor evidence."""

from __future__ import annotations

from fdai_service_contracts.ontology_query import QueryNodeKind

from fdai.core.ontology_platform.causal_competitors import CausalCompetitorSource
from fdai.core.ontology_platform.metric_semantics import (
    MetricSemanticRegistry,
    MetricWindowProvider,
)
from fdai.core.ontology_platform.query_execution import QueryNodeHandler
from fdai.core.ontology_platform.query_metric_handlers import (
    EvidenceJoinNodeHandler,
    MetricComparisonNodeHandler,
    MetricScopeSeriesNodeHandler,
    MetricSeriesNodeHandler,
)


def build_metric_query_handlers(
    *,
    registry: MetricSemanticRegistry,
    provider: MetricWindowProvider,
    competitor_source: CausalCompetitorSource | None = None,
) -> dict[QueryNodeKind, QueryNodeHandler]:
    """Bind existing metric nodes without inventing source or execution authority."""

    return {
        QueryNodeKind.METRIC_SERIES: MetricSeriesNodeHandler(
            registry=registry,
            provider=provider,
        ),
        QueryNodeKind.METRIC_SCOPE_SERIES: MetricScopeSeriesNodeHandler(
            registry=registry,
            provider=provider,
        ),
        QueryNodeKind.METRIC_COMPARISON: MetricComparisonNodeHandler(registry=registry),
        QueryNodeKind.EVIDENCE_JOIN: EvidenceJoinNodeHandler(
            competitor_source=competitor_source,
        ),
    }
