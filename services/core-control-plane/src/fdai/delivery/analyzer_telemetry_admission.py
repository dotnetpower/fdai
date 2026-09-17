"""Hold discovered analyzer targets when required telemetry has no bound source."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from fdai.delivery.analyzer_targets import SKIP_TELEMETRY_SOURCE_UNAVAILABLE
from fdai.delivery.azure.demo_queries import default_metric_queries
from fdai.delivery.azure.metrics_api_queries import azure_metrics_api_queries

ANALYZER_METRICS_BY_RESOURCE_TYPE: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "api-gateway": frozenset({"backend_latency_ms", "http_5xx_rate"}),
        "kubernetes-cluster": frozenset(
            {"node_cpu_percent", "pod_restart_count", "rollout_stall_duration_seconds"}
        ),
        "llm-endpoint": frozenset({"http_429_rate", "request_surge_ratio"}),
        "mysql-server": frozenset({"active_connections", "cpu_percent"}),
        "network.application-gateway": frozenset(
            {"backend_first_byte_response_time_ms", "healthy_host_count"}
        ),
    }
)


def discovered_telemetry_holds(*, monitor_workspace_id: str | None) -> dict[str, str]:
    """Return deterministic holds for discovered targets without complete telemetry."""

    supported_metrics = set(azure_metrics_api_queries())
    if monitor_workspace_id is not None:
        supported_metrics.update(default_metric_queries())
    return {
        resource_type: SKIP_TELEMETRY_SOURCE_UNAVAILABLE
        for resource_type, required_metrics in ANALYZER_METRICS_BY_RESOURCE_TYPE.items()
        if not required_metrics.issubset(supported_metrics)
    }


__all__ = ["ANALYZER_METRICS_BY_RESOURCE_TYPE", "discovered_telemetry_holds"]
