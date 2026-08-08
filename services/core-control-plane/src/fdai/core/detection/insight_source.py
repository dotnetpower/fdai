"""MetricProvider bridge for catalog-driven operational insights."""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta

from fdai.core.detection.insights import (
    InsightObservation,
    InsightOperator,
    OperationalInsightEngine,
    OperationalInsightFinding,
)
from fdai.shared.providers.metric import MetricProvider, MetricProviderError, MetricQuery

_RESOURCE_LABEL = "resource_id"


class OperationalInsightSource:
    """Fetch each required metric once and evaluate an insight catalog."""

    def __init__(
        self,
        metric_provider: MetricProvider,
        *,
        resource_label: str = _RESOURCE_LABEL,
    ) -> None:
        self._provider = metric_provider
        self._resource_label = resource_label

    async def evaluate(
        self,
        engine: OperationalInsightEngine,
        *,
        resource_ref: str,
        since: datetime,
        until: datetime,
        window_bucket: str,
    ) -> tuple[OperationalInsightFinding, ...]:
        """Fetch normalized telemetry and return every fired recipe."""
        metric_names = {
            metric_name
            for recipe in engine.recipes
            for metric_name in (recipe.metric, recipe.comparison_metric)
            if metric_name is not None
        }
        values: dict[str, float] = {}
        previous_values: dict[str, float] = {}
        baseline_values: dict[str, float] = {}
        sample_counts: dict[str, int] = {}
        last_seen_at: dict[str, datetime] = {}
        unavailable_metrics: set[str] = set()

        for metric_name in sorted(metric_names):
            query_since = _query_since(engine, metric_name=metric_name, since=since, until=until)
            try:
                points = [
                    point
                    async for point in self._provider.query(
                        MetricQuery(
                            metric_name=metric_name,
                            labels={self._resource_label: resource_ref},
                            since=query_since,
                            until=until,
                        )
                    )
                    if math.isfinite(point.value)
                ]
            except MetricProviderError:
                unavailable_metrics.add(metric_name)
                continue
            points.sort(key=lambda point: point.at)
            sample_counts[metric_name] = len(points)
            if not points:
                continue
            current = points[-1]
            values[metric_name] = current.value
            last_seen_at[metric_name] = current.at
            if len(points) >= 2:
                previous_values[metric_name] = points[-2].value
                baseline_values[metric_name] = statistics.fmean(
                    point.value for point in points[:-1]
                )

        return engine.evaluate(
            InsightObservation(
                resource_ref=resource_ref,
                window_bucket=window_bucket,
                values=values,
                previous_values=previous_values,
                baseline_values=baseline_values,
                sample_counts=sample_counts,
                last_seen_at=last_seen_at,
                unavailable_metrics=frozenset(unavailable_metrics),
                evaluated_at=until,
            )
        )


def _query_since(
    engine: OperationalInsightEngine,
    *,
    metric_name: str,
    since: datetime,
    until: datetime,
) -> datetime:
    stale_thresholds = [
        recipe.threshold
        for recipe in engine.recipes
        if recipe.metric == metric_name and recipe.operator is InsightOperator.STALE
    ]
    if not stale_thresholds:
        return since
    # Keep a bounded evidence window beyond the threshold. Querying only to
    # ``threshold + 1`` loses an already-stale last point, while an unbounded
    # query would make every scheduled tick scan the full telemetry history.
    stale_since = until - timedelta(seconds=max(stale_thresholds) * 2.0)
    return min(since, stale_since)


__all__ = ["OperationalInsightSource"]
