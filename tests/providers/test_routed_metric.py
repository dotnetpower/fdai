"""Tests for the routed / composite metric provider seam."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from fdai.shared.providers.metric import (
    MetricPoint,
    MetricProviderError,
    MetricQuery,
    NoopMetricProvider,
    StaticMetricProvider,
)
from fdai.shared.providers.routed_metric import (
    MetricRoute,
    RoutedMetricProvider,
    route_summary,
)


def _sample(name: str, value: float) -> MetricPoint:
    return MetricPoint(
        metric_name=name,
        at=datetime(2026, 7, 12, 23, 0, 0, tzinfo=UTC),
        value=value,
        labels={"resource_id": "res-1"},
    )


def test_metric_route_rejects_empty_supported_set() -> None:
    with pytest.raises(ValueError, match="supported_metrics MUST be non-empty"):
        MetricRoute(provider=NoopMetricProvider(), supported_metrics=frozenset())


def test_routed_provider_rejects_empty_routing_table() -> None:
    with pytest.raises(ValueError, match="requires >= 1 route"):
        RoutedMetricProvider(routes=())


async def _collect(provider: RoutedMetricProvider, name: str) -> list[MetricPoint]:
    got: list[MetricPoint] = []
    async for point in provider.query(MetricQuery(metric_name=name)):
        got.append(point)
    return got


async def test_primary_wins_the_overlap() -> None:
    """When the same metric is in both routes, the FIRST route serves it."""
    primary = StaticMetricProvider([_sample("shared", 1.0)])
    fallback = StaticMetricProvider([_sample("shared", 999.0)])
    routed = RoutedMetricProvider(
        routes=(
            MetricRoute(provider=primary, supported_metrics=frozenset({"shared"})),
            MetricRoute(provider=fallback, supported_metrics=frozenset({"shared"})),
        ),
    )
    got = await _collect(routed, "shared")
    assert [p.value for p in got] == [1.0]


async def test_fallback_serves_metrics_the_primary_does_not_declare() -> None:
    """A metric only the fallback lists still resolves - Prom-primary /
    AML-fallback pattern in miniature."""
    prom = StaticMetricProvider([_sample("node_cpu_percent", 42.0)])
    aml = StaticMetricProvider(
        [
            _sample("node_cpu_percent", 999.0),  # would collide, but Prom wins
            _sample("cpu_percent", 55.0),
        ]
    )
    routed = RoutedMetricProvider(
        routes=(
            MetricRoute(provider=prom, supported_metrics=frozenset({"node_cpu_percent"})),
            MetricRoute(
                provider=aml,
                supported_metrics=frozenset({"node_cpu_percent", "cpu_percent"}),
            ),
        ),
    )
    assert [p.value for p in await _collect(routed, "node_cpu_percent")] == [42.0]
    assert [p.value for p in await _collect(routed, "cpu_percent")] == [55.0]


async def test_unrouted_metric_fails_closed() -> None:
    """Fail-closed on a name no route declares - the caller MUST NOT
    silently get an empty result set that looks like `absent evidence`."""
    routed = RoutedMetricProvider(
        routes=(
            MetricRoute(
                provider=StaticMetricProvider([]),
                supported_metrics=frozenset({"only_this"}),
            ),
        ),
    )
    with pytest.raises(MetricProviderError, match="no route serves metric"):
        async for _ in routed.query(MetricQuery(metric_name="unknown_metric")):
            pass


def test_routed_metrics_returns_union() -> None:
    routed = RoutedMetricProvider(
        routes=(
            MetricRoute(
                provider=NoopMetricProvider(),
                supported_metrics=frozenset({"a", "b"}),
            ),
            MetricRoute(
                provider=NoopMetricProvider(),
                supported_metrics=frozenset({"b", "c"}),
            ),
        ),
    )
    assert routed.routed_metrics() == frozenset({"a", "b", "c"})


def test_route_for_reports_which_provider_serves_a_metric() -> None:
    routed = RoutedMetricProvider(
        routes=(
            MetricRoute(
                provider=StaticMetricProvider([]),
                supported_metrics=frozenset({"a"}),
            ),
            MetricRoute(provider=NoopMetricProvider(), supported_metrics=frozenset({"b"})),
        ),
    )
    assert routed.route_for("a") == "StaticMetricProvider"
    assert routed.route_for("b") == "NoopMetricProvider"
    assert routed.route_for("missing") is None


def test_route_summary_is_none_for_a_non_routed_provider() -> None:
    """The helper is defensive so a caller does not need an isinstance guard."""
    assert route_summary(NoopMetricProvider()) is None


def test_route_summary_maps_every_declared_metric() -> None:
    prom = StaticMetricProvider([])
    aml = NoopMetricProvider()
    routed = RoutedMetricProvider(
        routes=(
            MetricRoute(provider=prom, supported_metrics=frozenset({"node_cpu_percent"})),
            MetricRoute(
                provider=aml,
                supported_metrics=frozenset({"node_cpu_percent", "cpu_percent"}),
            ),
        ),
    )
    summary = route_summary(routed)
    assert summary == {
        "node_cpu_percent": "StaticMetricProvider",  # Prom wins the overlap
        "cpu_percent": "NoopMetricProvider",
    }


async def test_iteration_is_bounded_by_the_chosen_provider() -> None:
    """A misbehaving downstream provider does not double-yield across routes.

    Once a route is picked, ALL of its samples are yielded and no other
    route ever runs - the dispatch is exclusive per query."""
    primary_calls: list[str] = []

    class _RecordingProvider:
        async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
            primary_calls.append(query.metric_name)
            yield _sample(query.metric_name, 7.0)

    fallback_calls: list[str] = []

    class _FallbackProvider:
        async def query(
            self, query: MetricQuery
        ) -> AsyncIterator[MetricPoint]:  # pragma: no cover - MUST NOT run
            fallback_calls.append(query.metric_name)
            yield _sample(query.metric_name, 8.0)

    routed = RoutedMetricProvider(
        routes=(
            MetricRoute(provider=_RecordingProvider(), supported_metrics=frozenset({"m"})),
            MetricRoute(
                provider=_FallbackProvider(),
                supported_metrics=frozenset({"m"}),
            ),
        ),
    )
    got = await _collect(routed, "m")
    assert [p.value for p in got] == [7.0]
    assert primary_calls == ["m"]
    assert fallback_calls == []
