"""One analyzer tick end to end over a routed metric provider.

Proves the pull baseline in
``docs/roadmap/rules-and-detection/near-real-time-detection-paths.md``: the tick
resolves targets, reaches the backend the routing table selects for each metric,
and turns a breach into one canonical Event on the ingest topic. Nothing here
executes a change.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.investigation import InvestigationCoordinator, default_analyzers
from fdai.delivery.analyzer_targets import resolve_analyzer_targets
from fdai.delivery.analyzer_tick import (
    ANALYZER_EVENT_SOURCE,
    ANALYZER_EVENT_TOPIC,
    AnalyzerTarget,
    AnalyzerTickRunner,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.metric import MetricPoint, MetricQuery
from fdai.shared.providers.routed_metric import MetricRoute, RoutedMetricProvider

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)

_PROMETHEUS_METRICS = frozenset({"node_cpu_percent", "pod_restart_count"})
_MONITOR_LOGS_METRICS = frozenset(
    {
        "rollout_stall_duration_seconds",
        "cpu_percent",
        "active_connections",
        "http_429_rate",
        "request_surge_ratio",
        "backend_first_byte_response_time_ms",
        "healthy_host_count",
        "http_5xx_rate",
        "backend_latency_ms",
    }
)


class StubBackend:
    """One telemetry backend that records the queries the router sent it."""

    def __init__(self, name: str, values: dict[str, float]) -> None:
        self.name = name
        self._values = values
        self.queries: list[str] = []

    async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
        self.queries.append(query.metric_name)
        value = self._values.get(query.metric_name)
        if value is None:
            return
        yield MetricPoint(
            metric_name=query.metric_name,
            at=NOW - timedelta(seconds=30),
            value=value,
            labels=dict(query.labels),
        )


class RecordingBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, dict[str, object]]] = []

    async def publish(self, topic: str, key: str, payload: dict[str, object]) -> None:
        self.published.append((topic, key, payload))


def _routed() -> tuple[RoutedMetricProvider, StubBackend, StubBackend]:
    prometheus = StubBackend("prometheus", {"node_cpu_percent": 93.0, "pod_restart_count": 0.0})
    monitor_logs = StubBackend("monitor_logs", {"cpu_percent": 95.0, "active_connections": 12.0})
    provider = RoutedMetricProvider(
        (
            MetricRoute(provider=prometheus, supported_metrics=_PROMETHEUS_METRICS),
            MetricRoute(provider=monitor_logs, supported_metrics=_MONITOR_LOGS_METRICS),
        )
    )
    return provider, prometheus, monitor_logs


def _runner(provider: RoutedMetricProvider, bus: RecordingBus) -> AnalyzerTickRunner:
    return AnalyzerTickRunner(
        coordinator=InvestigationCoordinator(
            analyzers=default_analyzers(provider, wall_clock=lambda: NOW)
        ),
        event_bus=bus,  # type: ignore[arg-type]
        window_seconds=300,
        clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_one_tick_reaches_each_routed_backend_and_publishes_its_breach() -> None:
    provider, prometheus, monitor_logs = _routed()
    bus = RecordingBus()

    report = await _runner(provider, bus).run_once(
        (
            AnalyzerTarget(resource_ref="res-aks", resource_kind="aks_cluster"),
            AnalyzerTarget(resource_ref="res-mysql", resource_kind="mysql_flexible_server"),
        )
    )

    assert report.targets == 2
    assert not report.failed
    assert report.analyzer_errors == ()
    assert "node_cpu_percent" in prometheus.queries
    assert "cpu_percent" in monitor_logs.queries
    assert "node_cpu_percent" not in monitor_logs.queries

    published = {payload["event_type"]: payload for _, _, payload in bus.published}
    assert set(published) == {"analyzer.node_cpu.observed", "analyzer.db_cpu.observed"}
    node_cpu = published["analyzer.node_cpu.observed"]
    assert node_cpu["source"] == ANALYZER_EVENT_SOURCE
    assert node_cpu["mode"] == Mode.SHADOW.value
    assert node_cpu["resource_ref"] == "res-aks"
    assert bus.published[0][0] == ANALYZER_EVENT_TOPIC
    assert provider.route_for("node_cpu_percent") == "StubBackend"


@pytest.mark.asyncio
async def test_a_healthy_routed_pass_publishes_nothing() -> None:
    aks_metrics = _PROMETHEUS_METRICS | frozenset({"rollout_stall_duration_seconds"})
    prometheus = StubBackend(
        "prometheus",
        {
            "node_cpu_percent": 10.0,
            "pod_restart_count": 0.0,
            "rollout_stall_duration_seconds": 0.0,
        },
    )
    provider = RoutedMetricProvider(
        (MetricRoute(provider=prometheus, supported_metrics=aks_metrics),)
    )
    bus = RecordingBus()

    report = await _runner(provider, bus).run_once(
        (AnalyzerTarget(resource_ref="res-aks", resource_kind="aks_cluster"),)
    )

    assert report.findings == 0
    assert report.analyzer_errors == ()
    assert bus.published == []


@pytest.mark.asyncio
async def test_an_unrouted_metric_marks_the_pass_partial_instead_of_healthy() -> None:
    prometheus = StubBackend("prometheus", {"node_cpu_percent": 10.0, "pod_restart_count": 0.0})
    provider = RoutedMetricProvider(
        (MetricRoute(provider=prometheus, supported_metrics=_PROMETHEUS_METRICS),)
    )
    bus = RecordingBus()

    report = await _runner(provider, bus).run_once(
        (AnalyzerTarget(resource_ref="res-aks", resource_kind="aks_cluster"),)
    )

    assert bus.published == []
    assert report.analyzer_errors[0][0] == "res-aks"
    assert "MetricProviderError" in report.analyzer_errors[0][1]


@pytest.mark.asyncio
async def test_resolved_inventory_targets_drive_the_same_routed_tick() -> None:
    provider, prometheus, _ = _routed()
    bus = RecordingBus()
    configured = (AnalyzerTarget(resource_ref="res-aks", resource_kind="aks_cluster"),)

    resolution = await resolve_analyzer_targets(configured=configured, store=None, now=NOW)
    report = await _runner(provider, bus).run_once(resolution.targets)

    assert resolution.inventory_consulted is False
    assert report.published == 1
    assert prometheus.queries.count("node_cpu_percent") == 1
