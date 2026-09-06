"""Native Azure metrics bind independently of the optional Logs workspace."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import httpx
import pytest
from fdai.composition import Container
from fdai.composition.wire_azure import AzureWireOverrides
from fdai.composition.wire_metric_provider import attach_metric_provider
from fdai.core.operator_memory import InMemoryOperatorMemoryStore
from fdai.delivery.azure.metrics_api import AzureMonitorMetricsProvider, MetricsApiTemplate
from fdai.shared.providers.routed_metric import RoutedMetricProvider
from fdai.shared.providers.workload_identity import WorkloadIdentity


def test_azure_override_accepts_native_templates_without_a_logs_workspace() -> None:
    templates = {"custom": MetricsApiTemplate("Requests", "Total")}
    overrides = AzureWireOverrides(
        endpoint="https://example.com",
        catalog_root=Path("rule-catalog"),
        operator_memory_store=InMemoryOperatorMemoryStore(),
        metrics_api_queries=templates,
    )
    assert overrides.metrics_api_queries == templates
    assert overrides.monitor_workspace_id is None


def test_azure_override_keeps_logs_workspace_requirement() -> None:
    with pytest.raises(ValueError, match="monitor_queries requires"):
        AzureWireOverrides(
            endpoint="https://example.com",
            catalog_root=Path("rule-catalog"),
            operator_memory_store=InMemoryOperatorMemoryStore(),
            monitor_queries={},
        )


async def test_native_metrics_bind_without_logs_workspace(container: Container) -> None:
    original = container.metric_provider
    async with httpx.AsyncClient() as client:
        bound = attach_metric_provider(
            container,
            identity=cast(WorkloadIdentity, object()),
            http_client=client,
            monitor_workspace_id=None,
            monitor_queries=None,
            metrics_api_queries=None,
            prometheus_base_url=None,
            prometheus_queries=None,
            prometheus_audience=None,
        )
    assert isinstance(bound.metric_provider, AzureMonitorMetricsProvider)
    assert container.metric_provider is original


async def test_native_override_needs_no_workspace_and_empty_override_fails(
    container: Container,
) -> None:
    async with httpx.AsyncClient() as client:
        bound = attach_metric_provider(
            container,
            identity=cast(WorkloadIdentity, object()),
            http_client=client,
            monitor_workspace_id=None,
            monitor_queries=None,
            metrics_api_queries={"custom": MetricsApiTemplate("Requests", "Total")},
            prometheus_base_url=None,
            prometheus_queries=None,
            prometheus_audience=None,
        )
        assert isinstance(bound.metric_provider, AzureMonitorMetricsProvider)
        with pytest.raises(ValueError, match="templates MUST be non-empty"):
            attach_metric_provider(
                container,
                identity=cast(WorkloadIdentity, object()),
                http_client=client,
                monitor_workspace_id=None,
                monitor_queries=None,
                metrics_api_queries={},
                prometheus_base_url=None,
                prometheus_queries=None,
                prometheus_audience=None,
            )


async def test_route_order_preserves_prometheus_native_then_logs(container: Container) -> None:
    async with httpx.AsyncClient() as client:
        bound = attach_metric_provider(
            container,
            identity=cast(WorkloadIdentity, object()),
            http_client=client,
            monitor_workspace_id="example-workspace",
            monitor_queries=None,
            metrics_api_queries=None,
            prometheus_base_url="https://example.com",
            prometheus_queries=None,
            prometheus_audience=None,
        )
    provider = bound.metric_provider
    assert isinstance(provider, RoutedMetricProvider)
    assert provider.route_for("node_cpu_percent") == "PrometheusMetricProvider"
    assert provider.route_for("backend_latency_ms") == "AzureMonitorMetricsProvider"
    assert provider.route_for("model.response.429.count") == "AzureMonitorMetricsProvider"
    assert provider.route_for("gateway.total_time") == "AzureMonitorMetricsProvider"
    assert provider.route_for("http_429_rate") == "AzureMonitorLogsMetricProvider"
