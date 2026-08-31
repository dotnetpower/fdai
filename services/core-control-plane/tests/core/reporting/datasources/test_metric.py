"""Coverage for provider-neutral metric report projections."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from fdai.core.reporting.datasources.metric import MetricDataSource
from fdai.core.reporting.models import QuerySpec
from fdai.shared.providers.metric import MetricPoint, MetricQuery

_NOW = datetime(2026, 8, 31, tzinfo=UTC)


class _Provider:
    def __init__(self, points: tuple[MetricPoint, ...]) -> None:
        self.points = points
        self.queries: list[MetricQuery] = []

    async def _stream(self) -> AsyncIterator[MetricPoint]:
        for point in self.points:
            yield point

    def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
        self.queries.append(query)
        return self._stream()


def _point(value: float, minute: int, **labels: str) -> MetricPoint:
    return MetricPoint(
        metric_name="latency",
        at=_NOW + timedelta(minutes=minute),
        value=value,
        labels=labels,
    )


async def test_metric_datasource_projects_all_supported_shapes() -> None:
    provider = _Provider(
        (
            _point(1, 2, region="west"),
            _point(3, 1, region="west"),
            _point(5, 3),
        )
    )
    source = MetricDataSource(provider=provider, name="metrics")
    window = {"since": _NOW, "until": _NOW + timedelta(hours=1), "variables": {}}

    missing = await source.query(QuerySpec("metrics"), **window)
    scalar = await source.query(
        QuerySpec(
            "metrics",
            {
                "metric_name": "latency",
                "labels": {"service": 7},
                "aggregation": "sum",
                "projection": "scalar_sum",
            },
        ),
        **window,
    )
    series = await source.query(
        QuerySpec("metrics", {"metric_name": "latency", "group_by": "invalid"}),
        **window,
    )
    grouped = await source.query(
        QuerySpec("metrics", {"metric_name": "latency", "group_by": ["region"]}),
        **window,
    )
    percentiles = await source.query(
        QuerySpec("metrics", {"metric_name": "latency", "projection": "percentiles"}),
        **window,
    )

    assert source.name == "metrics"
    assert missing.metadata == {"error": "metric_name required"}
    assert scalar.scalar == 9
    assert scalar.metadata == {"sample_count": 3}
    assert series.series[0].label == "all"
    assert grouped.series[0].label == "west"
    assert grouped.series[0].points == (
        ((_NOW + timedelta(minutes=1)).timestamp(), 3),
        ((_NOW + timedelta(minutes=2)).timestamp(), 1),
    )
    assert grouped.series[1].label == "all"
    assert [row["percentile"] for row in percentiles.rows] == ["p50", "p90", "p95", "p99"]
    assert provider.queries[0].labels == {"service": "7"}
    assert provider.queries[0].aggregation == "sum"


async def test_percentiles_projection_handles_empty_provider() -> None:
    source = MetricDataSource(provider=_Provider(()))

    result = await source.query(
        QuerySpec("metrics", {"metric_name": "latency", "projection": "percentiles"}),
        since=_NOW,
        until=_NOW + timedelta(hours=1),
        variables={},
    )

    assert result.rows == ()
    assert result.metadata == {"sample_count": 0}
