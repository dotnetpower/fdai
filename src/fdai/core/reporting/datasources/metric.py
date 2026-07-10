"""Metric datasource - wraps ``shared.providers.metric.MetricProvider``.

Consumes any CSP-neutral metric backend (Prometheus, Log Analytics KQL,
Datadog metrics) via the async provider seam. Returns
:class:`~fdai.core.reporting.models.Series` groups suitable for the
``timeseries`` / ``heatmap`` widgets, or a summed scalar suitable for
``query_value``.

Query parameters:

- ``metric_name`` (str, required): CSP-neutral metric name forwarded to
  :class:`~fdai.shared.providers.metric.MetricQuery.metric_name`.
- ``labels`` (mapping, optional): pre-filter labels forwarded to the
  provider.
- ``aggregation`` (str, optional): vendor-neutral hint (``sum`` /
  ``avg`` / ``min`` / ``max`` / ``p50`` / ``p90`` / ``p99``); the
  adapter MAY ignore it.
- ``group_by`` (list[str], optional): label keys used to bucket the
  returned points into named series; when absent, all points collapse
  into a single ``"all"`` series.
- ``projection`` (str, default ``series``): ``"series"`` for the
  timeseries shape, ``"scalar_sum"`` for a single summed value.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from fdai.core.reporting.models import DataSet, QuerySpec, Series
from fdai.shared.providers.metric import (
    MetricPoint,
    MetricProvider,
    MetricQuery,
)


class MetricDataSource:
    """Projection over :class:`~fdai.shared.providers.metric.MetricProvider`."""

    __slots__ = ("_name", "_provider")

    def __init__(self, *, provider: MetricProvider, name: str = "metric") -> None:
        self._name = name
        self._provider = provider

    @property
    def name(self) -> str:
        return self._name

    async def query(
        self,
        spec: QuerySpec,
        *,
        since: datetime,
        until: datetime,
        variables: Mapping[str, str],
    ) -> DataSet:
        del variables
        params = spec.parameters
        metric_name = str(params.get("metric_name") or "")
        if not metric_name:
            return DataSet(metadata={"error": "metric_name required"})

        labels_raw = params.get("labels") or {}
        labels: dict[str, str] = {str(k): str(v) for k, v in _as_mapping(labels_raw).items()}
        aggregation = params.get("aggregation")
        agg_str = str(aggregation) if aggregation is not None else None
        group_by = _as_sequence(params.get("group_by"))
        projection = str(params.get("projection", "series"))

        query = MetricQuery(
            metric_name=metric_name,
            labels=labels,
            since=since,
            until=until,
            aggregation=agg_str,
        )

        points: list[MetricPoint] = []
        async for point in self._provider.query(query):
            points.append(point)

        if projection == "scalar_sum":
            total = sum(p.value for p in points)
            return DataSet(scalar=total, metadata={"sample_count": len(points)})

        # Default: series projection.
        return _series_dataset(points, group_by=group_by)


def _series_dataset(points: Sequence[MetricPoint], *, group_by: Sequence[str]) -> DataSet:
    if not group_by:
        pts = tuple((p.at.timestamp(), p.value) for p in points)
        return DataSet(series=(Series(label="all", points=pts, labels={}),))

    grouped: dict[tuple[str, ...], list[tuple[float, float]]] = {}
    labels_per_group: dict[tuple[str, ...], dict[str, str]] = {}
    for point in points:
        key = tuple(str(point.labels.get(g, "")) for g in group_by)
        grouped.setdefault(key, []).append((point.at.timestamp(), point.value))
        if key not in labels_per_group:
            labels_per_group[key] = {g: str(point.labels.get(g, "")) for g in group_by}

    series = tuple(
        Series(
            label=" / ".join(labels_per_group[key].values()) or "all",
            points=tuple(sorted(pts)),
            labels=labels_per_group[key],
        )
        for key, pts in grouped.items()
    )
    return DataSet(series=series)


def _as_mapping(raw: Any) -> Mapping[str, Any]:
    if isinstance(raw, Mapping):
        return raw
    return {}


def _as_sequence(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, (list, tuple)):
        return tuple(str(item) for item in raw)
    return ()


__all__ = ["MetricDataSource"]
