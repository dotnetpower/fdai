"""Reviewed metric semantic catalog and provider binding tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fdai.core.ontology_platform.metric_semantics import (
    CausalJoinStatus,
    join_causal_evidence,
)
from fdai.core.rca.temporal_causality import TemporalCausalityConfig
from fdai.delivery.metric_window import ProviderMetricWindowReader
from fdai.runtime.metric_semantic_catalog import load_metric_semantic_registry
from fdai.shared.providers.metric import (
    MetricPoint,
    MetricProviderError,
    MetricQuery,
    StaticMetricProvider,
)

ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 8, 10, tzinfo=UTC)


def test_shipped_metric_semantics_load_without_language_aliases() -> None:
    registry = load_metric_semantic_registry(ROOT / "rule-catalog/vocabulary/metric-semantics.yaml")

    assert set(registry.definitions) >= {
        "database.mysql.active_connections",
        "database.mysql.cpu.utilization_pct",
        "database.mysql.query.count",
        "database.mysql.slow_query.count",
        "request.volume",
        "request.errors",
        "request.timeout",
        "resource.cpu.utilization_pct",
        "resource.activation.failure",
        "storage.write.success",
        "network.change",
        "pod.restart.history",
        "resource.memory.available_pct",
        "resource.memory.usage_pct",
    }
    assert not hasattr(registry.resolve("request.volume"), "aliases")
    assert (
        registry.resolve("resource.memory.available_pct").provider_metric
        == "host.memory.available_pct"
    )
    memory_usage = registry.resolve("resource.memory.usage_pct")
    assert memory_usage.provider_metric == "container_app_memory_percentage"
    assert memory_usage.canonical_unit == "percent"
    assert memory_usage.aggregation.value == "average"
    timeout = registry.resolve("request.timeout")
    assert timeout.provider_metric == "container_app_resiliency_request_timeouts"
    assert timeout.canonical_unit == "count"
    assert timeout.aggregation.value == "sum"
    activation = registry.resolve("resource.activation.failure")
    assert activation.provider_metric == "container_app_activation_failure_count"
    assert activation.canonical_unit == "count"
    pod_restart = registry.resolve("pod.restart.history")
    assert pod_restart.provider_metric == "k8s.pod.restarts"
    assert pod_restart.scope_label_selectors == {
        "pod_uid": ("properties", "properties", "uid"),
        "resource_id": ("properties", "properties", "cluster_ref"),
    }
    vm_cpu = registry.resolve("resource.cpu.utilization_pct")
    assert vm_cpu.provider_metric == "host.cpu.percent"
    assert vm_cpu.canonical_unit == "percent"
    assert vm_cpu.aggregation.value == "average"
    mysql_cpu = registry.resolve("database.mysql.cpu.utilization_pct")
    assert mysql_cpu.provider_metric == "cpu_percent"
    assert mysql_cpu.canonical_unit == "percent"
    assert mysql_cpu.aggregation.value == "average"
    mysql_connections = registry.resolve("database.mysql.active_connections")
    assert mysql_connections.provider_metric == "active_connections"
    assert mysql_connections.canonical_unit == "count"
    assert mysql_connections.aggregation.value == "maximum"
    assert registry.resolve("database.mysql.query.count").provider_metric == "Queries"
    assert registry.resolve("database.mysql.slow_query.count").provider_metric == "Slow_queries"


async def test_metric_provider_binding_preserves_zero_and_marks_empty_as_gap() -> None:
    registry = load_metric_semantic_registry(ROOT / "rule-catalog/vocabulary/metric-semantics.yaml")
    definition = registry.resolve("request.volume")
    reader = ProviderMetricWindowReader(
        provider=StaticMetricProvider(
            (
                MetricPoint(
                    metric_name=definition.provider_metric,
                    at=NOW,
                    value=0.0,
                    labels={"resource_id": "service-a"},
                ),
            )
        )
    )

    observed = await reader.read(
        definition=definition,
        resource_id="service-a",
        start=NOW,
        end=NOW + timedelta(minutes=5),
    )
    missing = await ProviderMetricWindowReader(provider=StaticMetricProvider(())).read(
        definition=definition,
        resource_id="service-a",
        start=NOW,
        end=NOW + timedelta(minutes=5),
    )

    assert observed.complete is True
    assert observed.samples[0].value == 0.0
    assert missing.complete is False
    assert missing.missing_reason == "provider_gap"


async def test_metric_provider_binding_uses_exact_scoped_labels() -> None:
    registry = load_metric_semantic_registry(ROOT / "rule-catalog/vocabulary/metric-semantics.yaml")
    definition = registry.resolve("pod.restart.history")
    labels = {"resource_id": "cluster-a", "pod_uid": "pod-uid-a"}
    reader = ProviderMetricWindowReader(
        provider=StaticMetricProvider(
            (
                MetricPoint(
                    metric_name=definition.provider_metric,
                    at=NOW,
                    value=2.0,
                    labels=labels,
                ),
            )
        )
    )

    result = await reader.read(
        definition=definition,
        resource_id="ontology-pod-a",
        start=NOW,
        end=NOW + timedelta(minutes=5),
        query_labels=labels,
    )

    assert result.complete is True
    assert result.resource_id == "ontology-pod-a"
    assert result.samples[0].value == 2.0


async def test_metric_provider_failure_becomes_explicit_unavailable_window() -> None:
    class UnavailableMetricProvider:
        async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
            del query
            raise MetricProviderError("provider unavailable")
            yield MetricPoint(  # pragma: no cover - retain the async iterator contract
                metric_name="unreachable",
                at=NOW,
                value=0.0,
            )

    registry = load_metric_semantic_registry(ROOT / "rule-catalog/vocabulary/metric-semantics.yaml")
    definition = registry.resolve("request.volume")

    result = await ProviderMetricWindowReader(provider=UnavailableMetricProvider()).read(
        definition=definition,
        resource_id="service-a",
        start=NOW,
        end=NOW + timedelta(minutes=5),
    )

    assert result.complete is False
    assert result.samples == ()
    assert result.missing_reason == "provider_unavailable"
    assert result.evidence_refs[0].startswith("metric-provider-unavailable:request.volume:")

    causal = join_causal_evidence(
        cause=result,
        effect=result,
        topology_change=None,
        feature_cutoff=NOW + timedelta(minutes=5),
        config=TemporalCausalityConfig(lag_seconds=(0,), min_samples=4),
        competing_explanations=("provider_outage",),
    )

    assert causal.status is CausalJoinStatus.UNRESOLVED
    assert "metric_window_incomplete" in causal.limitations
    assert causal.execution_authority is False
