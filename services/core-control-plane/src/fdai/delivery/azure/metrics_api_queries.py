"""Azure Monitor Metrics REST-API templates for the reference analyzer
metrics whose values live directly on the Azure resource.

Design contract: the fast intermediate route between Prometheus (AKS,
~15-60 s) and Log Analytics KQL (~2-5 min). The Metrics API queries
Azure Monitor's own metrics store per ARM id, so it is ~1-3 min behind
real-time (dramatically fresher than the Log Analytics
``AzureMetrics`` table path) without requiring a Log Analytics
workspace at all. Wired into the composition-root
:class:`~fdai.shared.providers.routed_metric.RoutedMetricProvider` as
route #2 in a Prom > Metrics > Logs chain so each analyzer call lands
on the fastest backend that can serve it.

Only the metrics whose CSP-neutral name maps **directly** onto an Azure
platform metric ship here - the ones that need computation
(``http_429_rate = throttled / total``, ``request_surge_ratio``,
``http_5xx_rate``) stay on the KQL fallback because the Metrics API
does not compose across metrics in a single call.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from fdai.delivery.azure.demo_queries import (
    METRIC_BACKEND_FIRST_BYTE_MS,
    METRIC_HEALTHY_HOST_COUNT,
    METRIC_MYSQL_ACTIVE_CONNECTIONS,
    METRIC_MYSQL_CPU_PERCENT,
)
from fdai.delivery.azure.metrics_api import MetricsApiTemplate

# MySQL Flexible Server - both live on the resource directly.
_MYSQL_CPU_PERCENT = MetricsApiTemplate(
    azure_metric_name="cpu_percent",
    aggregation="Average",
)

_MYSQL_ACTIVE_CONNECTIONS = MetricsApiTemplate(
    azure_metric_name="active_connections",
    aggregation="Maximum",
)

# Application Gateway - "backend first byte" is exposed as
# ``BackendLastByteResponseTime`` (millisecond average). Not a perfect
# rename but the analyzer's threshold (``GTE 2000 ms``) targets the same
# operator symptom (slow upstream). Healthy host count uses ``Minimum``
# to match the analyzer's ``LTE 1.0`` critical bound.
_APPGW_BACKEND_FIRST_BYTE = MetricsApiTemplate(
    azure_metric_name="BackendLastByteResponseTime",
    aggregation="Average",
)

_APPGW_HEALTHY_HOST_COUNT = MetricsApiTemplate(
    azure_metric_name="HealthyHostCount",
    aggregation="Minimum",
)


_ANALYZER_QUERIES: Mapping[str, MetricsApiTemplate] = MappingProxyType(
    {
        METRIC_MYSQL_CPU_PERCENT: _MYSQL_CPU_PERCENT,
        METRIC_MYSQL_ACTIVE_CONNECTIONS: _MYSQL_ACTIVE_CONNECTIONS,
        METRIC_BACKEND_FIRST_BYTE_MS: _APPGW_BACKEND_FIRST_BYTE,
        METRIC_HEALTHY_HOST_COUNT: _APPGW_HEALTHY_HOST_COUNT,
    }
)


def azure_metrics_api_queries() -> Mapping[str, MetricsApiTemplate]:
    """Return the CSP-neutral ``metric_name`` -> Azure Metrics API
    template map this adapter is authorized to serve.

    A fork that adds direct-mapped Azure metrics (APIM ``Duration`` for
    ``backend_latency_ms``, storage account ``Availability``, ...)
    copies this map and adds entries, then passes the result via
    ``AzureWireOverrides.metrics_api_queries``. Every key MUST also be
    a key the analyzers pass, or the metric adapter will fail-closed on
    a lookup miss.
    """
    return _ANALYZER_QUERIES


__all__ = [
    "azure_metrics_api_queries",
]
