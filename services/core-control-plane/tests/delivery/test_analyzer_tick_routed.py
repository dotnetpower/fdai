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
from traceback import format_exception

import pytest
from fdai.core.investigation import InvestigationCoordinator, default_analyzers
from fdai.delivery.analyzer_metric_provider import AnalyzerMetricProvider
from fdai.delivery.analyzer_targets import resolve_analyzer_targets
from fdai.delivery.analyzer_tick import (
    ANALYZER_EVENT_SOURCE,
    ANALYZER_EVENT_TOPIC,
    AnalyzerPublicationClaim,
    AnalyzerTarget,
    AnalyzerTickRunner,
)
from fdai.delivery.persistence.postgres_analyzer_publication import (
    PostgresAnalyzerPublicationLedger,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.event_bus import PublishReceipt
from fdai.shared.providers.metric import (
    MetricFailureReason,
    MetricPoint,
    MetricProvider,
    MetricProviderError,
    MetricQuery,
)
from fdai.shared.providers.routed_metric import MetricRoute, RoutedMetricProvider

from tests.delivery.publication_store import ConditionalStore

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
        self.requests: list[MetricQuery] = []

    async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
        self.queries.append(query.metric_name)
        self.requests.append(query)
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

    async def publish(self, topic: str, key: str, payload: dict[str, object]) -> PublishReceipt:
        self.published.append((topic, key, payload))
        return PublishReceipt(topic=topic, partition=0, offset=len(self.published) - 1)


class PublicationLedger:
    """Durable publication ledger over an in-memory compare-and-set store."""

    def __init__(self) -> None:
        self._inner = PostgresAnalyzerPublicationLedger(store=ConditionalStore())

    async def claim(self, idempotency_key: str) -> AnalyzerPublicationClaim:
        return await self._inner.claim(idempotency_key)

    async def mark_sending(
        self,
        idempotency_key: str,
        claim: AnalyzerPublicationClaim,
    ) -> AnalyzerPublicationClaim:
        return await self._inner.mark_sending(idempotency_key, claim)

    async def mark_uncertain(
        self,
        idempotency_key: str,
        claim: AnalyzerPublicationClaim,
        *,
        reason: str,
    ) -> AnalyzerPublicationClaim:
        return await self._inner.mark_uncertain(idempotency_key, claim, reason=reason)

    async def complete(
        self,
        idempotency_key: str,
        claim: AnalyzerPublicationClaim,
        receipt: PublishReceipt,
    ) -> None:
        await self._inner.complete(idempotency_key, claim, receipt)

    async def release(
        self,
        idempotency_key: str,
        claim: AnalyzerPublicationClaim,
        *,
        provably_unsent: bool = False,
    ) -> None:
        await self._inner.release(idempotency_key, claim, provably_unsent=provably_unsent)


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


def _runner(provider: MetricProvider, bus: RecordingBus) -> AnalyzerTickRunner:
    return AnalyzerTickRunner(
        coordinator=InvestigationCoordinator(
            analyzers=default_analyzers(provider, wall_clock=lambda: NOW)
        ),
        event_bus=bus,  # type: ignore[arg-type]
        publication_ledger=PublicationLedger(),
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
async def test_inventory_provider_identity_is_confined_to_metric_queries() -> None:
    routed, prometheus, monitor_logs = _routed()
    bus = RecordingBus()
    logical_ref = "scope-example/resource-group/example-rg/providers/aks/example-aks"
    provider_ref = (
        "/subscriptions/00000000-0000-0000-0000-000000000000/"
        "resourceGroups/example-rg/providers/Microsoft.ContainerService/"
        "managedClusters/example-aks"
    )
    target = AnalyzerTarget(
        resource_ref=logical_ref,
        resource_kind="aks_cluster",
        provider_query_ref=provider_ref,
    )
    provider = AnalyzerMetricProvider(
        routed,
        targets=(target,),
        normalize_provider_ref=str.casefold,
    )

    report = await _runner(provider, bus).run_once((target,))

    assert report.analyzer_errors == ()
    assert report.published == 1
    assert all(
        request.labels["resource_id"] == provider_ref.casefold()
        for request in (*prometheus.requests, *monitor_logs.requests)
    )
    assert bus.published[0][1] == logical_ref
    assert bus.published[0][2]["resource_ref"] == logical_ref
    assert provider_ref.casefold() not in str(bus.published).casefold()


@pytest.mark.asyncio
async def test_mapped_metric_points_restore_the_logical_resource_identity() -> None:
    backend = StubBackend("provider", {"node_cpu_percent": 93.0})
    logical_ref = "resource-logical"
    provider_ref = "/providers/example/resources/Provider-Resource"
    provider = AnalyzerMetricProvider(
        backend,
        targets=(
            AnalyzerTarget(
                resource_ref=logical_ref,
                resource_kind="aks_cluster",
                provider_query_ref=provider_ref,
            ),
        ),
        normalize_provider_ref=str.casefold,
    )

    points = [
        point
        async for point in provider.query(
            MetricQuery(metric_name="node_cpu_percent", labels={"resource_id": logical_ref})
        )
    ]

    assert backend.requests[0].labels["resource_id"] == provider_ref.casefold()
    assert points[0].labels["resource_id"] == logical_ref


@pytest.mark.asyncio
async def test_mapped_metric_provider_rejects_another_returned_resource() -> None:
    class WrongResourceBackend:
        async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
            yield MetricPoint(
                metric_name=query.metric_name,
                at=NOW,
                value=93.0,
                labels={"resource_id": "/providers/example/resources/other"},
            )

    provider = AnalyzerMetricProvider(
        WrongResourceBackend(),
        targets=(
            AnalyzerTarget(
                resource_ref="resource-logical",
                resource_kind="aks_cluster",
                provider_query_ref="/providers/example/resources/expected",
            ),
        ),
        normalize_provider_ref=str.casefold,
    )

    with pytest.raises(MetricProviderError, match="another mapped resource identity"):
        _ = [
            point
            async for point in provider.query(
                MetricQuery(
                    metric_name="node_cpu_percent",
                    labels={"resource_id": "resource-logical"},
                )
            )
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", list(MetricFailureReason))
@pytest.mark.parametrize("http_status", [None, 429, 503])
async def test_mapped_metric_provider_redacts_provider_identity_from_errors(
    reason: MetricFailureReason, http_status: int | None
) -> None:
    provider_ref = "/providers/example/resources/sensitive"

    class ProviderFailureError(MetricProviderError):
        @property
        def safe_context(self) -> str:
            return "private subclass diagnostic"

    class LeakingFailureBackend:
        async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
            if False:
                yield MetricPoint(metric_name=query.metric_name, at=NOW, value=0.0)
            raise ProviderFailureError(
                f"request failed for {query.labels['resource_id']} https://example.com/private",
                reason=reason,
                http_status=http_status,
            ) from RuntimeError("private response payload")

    provider = AnalyzerMetricProvider(
        LeakingFailureBackend(),
        targets=(
            AnalyzerTarget(
                resource_ref="resource-logical",
                resource_kind="aks_cluster",
                provider_query_ref=provider_ref,
            ),
        ),
    )

    with pytest.raises(MetricProviderError, match="mapped metric query failed") as captured:
        _ = [
            point
            async for point in provider.query(
                MetricQuery(
                    metric_name="node_cpu_percent",
                    labels={"resource_id": "resource-logical"},
                )
            )
        ]

    assert provider_ref not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert captured.value.reason is reason
    assert captured.value.http_status == http_status
    assert f"reason={reason.value}" in str(captured.value)
    if http_status is not None:
        assert f"http_status={http_status}" in str(captured.value)
    rendered = "".join(format_exception(captured.value))
    assert provider_ref not in rendered
    assert "https://example.com/private" not in rendered
    assert "private response payload" not in rendered
    assert "private subclass diagnostic" not in rendered


@pytest.mark.parametrize("resource_ref", [None, "unmapped", "resource-logical"])
async def test_legacy_provider_error_is_unknown_and_unmapped_behavior_is_unchanged(
    resource_ref: str | None,
) -> None:
    error = MetricProviderError("legacy provider failure")

    class FailingBackend:
        async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
            if False:
                yield MetricPoint(metric_name=query.metric_name, at=NOW, value=0.0)
            raise error

    provider = AnalyzerMetricProvider(
        FailingBackend(),
        targets=(
            AnalyzerTarget(
                resource_ref="resource-logical",
                resource_kind="aks_cluster",
                provider_query_ref="/providers/example/resources/private",
            ),
        ),
    )
    query = MetricQuery(
        metric_name="node_cpu_percent",
        labels={} if resource_ref is None else {"resource_id": resource_ref},
    )
    with pytest.raises(MetricProviderError) as caught:
        _ = [point async for point in provider.query(query)]

    assert caught.value.reason is MetricFailureReason.UNKNOWN
    assert caught.value.http_status is None
    if resource_ref == "resource-logical":
        assert "reason=unknown" in str(caught.value)
        assert "legacy provider failure" not in str(caught.value)
        assert caught.value.__cause__ is caught.value.__context__ is None
    else:
        assert caught.value is error
        assert str(caught.value) == "legacy provider failure"


def test_mapped_metric_provider_rejects_provider_identity_aliases() -> None:
    with pytest.raises(ValueError, match="multiple logical resources"):
        AnalyzerMetricProvider(
            StubBackend("provider", {}),
            targets=(
                AnalyzerTarget(
                    resource_ref="resource-a",
                    resource_kind="aks_cluster",
                    provider_query_ref="/providers/example/resources/shared",
                ),
                AnalyzerTarget(
                    resource_ref="resource-b",
                    resource_kind="aks_cluster",
                    provider_query_ref="/PROVIDERS/EXAMPLE/RESOURCES/SHARED",
                ),
            ),
            normalize_provider_ref=str.casefold,
        )


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
    configured = (
        AnalyzerTarget(
            resource_ref="res-aks",
            resource_kind="aks_cluster",
            provider_query_ref="/providers/example/resources/res-aks",
        ),
    )

    resolution = await resolve_analyzer_targets(configured=configured, store=None, now=NOW)
    report = await _runner(provider, bus).run_once(resolution.targets)

    assert resolution.inventory_consulted is False
    assert report.published == 1
    assert prometheus.queries.count("node_cpu_percent") == 1
