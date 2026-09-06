"""Azure Monitor Metrics REST-API templates for reviewed metrics whose
values live directly on the Azure resource.

Design contract: the fast intermediate route between Prometheus (AKS,
~15-60 s) and Log Analytics KQL (~2-5 min). The Metrics API queries
Azure Monitor's own metrics store per ARM id, so it is ~1-3 min behind
real-time (dramatically fresher than the Log Analytics
``AzureMetrics`` table path) without requiring a Log Analytics
workspace at all. Wired into the composition-root
:class:`~fdai.shared.providers.routed_metric.RoutedMetricProvider` as
route #2 in a Prom > Metrics > Logs chain so each analyzer call lands
on the fastest backend that can serve it.

Only metrics whose CSP-neutral name maps **directly** onto an Azure platform
metric ship here, including exact-target semantic investigation evidence. The
ones that need computation
(``http_429_rate = throttled / total``, ``request_surge_ratio``,
``http_5xx_rate``) stay on the KQL fallback because the Metrics API
does not compose across metrics in a single call.

Platform identifiers and supported aggregations follow the Azure Monitor
supported-metrics references for Microsoft.Network/applicationGateways,
Microsoft.ApiManagement/service, and Microsoft.CognitiveServices/accounts.
Availability still depends on resource kind and existing provider evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from fdai.delivery.azure.demo_queries import (
    METRIC_APIM_BACKEND_LATENCY_MS,
    METRIC_BACKEND_FIRST_BYTE_MS,
    METRIC_CONTAINER_APP_CPU_NANOCORES,
    METRIC_CONTAINER_APP_MEMORY_PERCENT,
    METRIC_CONTAINER_APP_REQUEST_TIMEOUTS,
    METRIC_HEALTHY_HOST_COUNT,
    METRIC_MYSQL_ACTIVE_CONNECTIONS,
    METRIC_MYSQL_CPU_PERCENT,
    METRIC_SERVICE_REQUEST_DURATION_MS,
)
from fdai.delivery.azure.metrics_api import MetricsApiDimensionFilter, MetricsApiTemplate

_APPGW_TYPE = "Microsoft.Network/applicationGateways"
_APIM_TYPE = "Microsoft.ApiManagement/service"
_MODEL_TYPE = "Microsoft.CognitiveServices/accounts"

# MySQL Flexible Server - both live on the resource directly.
_MYSQL_CPU_PERCENT = MetricsApiTemplate(
    azure_metric_name="cpu_percent",
    aggregation="Average",
)

_MYSQL_ACTIVE_CONNECTIONS = MetricsApiTemplate(
    azure_metric_name="active_connections",
    aggregation="Maximum",
)

# First-byte and last-byte durations are distinct Azure metrics. Healthy host
# count supports Average, not Minimum; analyzer thresholds do not change units
# or authorize an unsupported platform aggregation.
_APPGW_BACKEND_FIRST_BYTE = MetricsApiTemplate(
    azure_metric_name="BackendFirstByteResponseTime",
    aggregation="Average",
    resource_type=_APPGW_TYPE,
)

_APPGW_HEALTHY_HOST_COUNT = MetricsApiTemplate(
    azure_metric_name="HealthyHostCount",
    aggregation="Average",
    resource_type=_APPGW_TYPE,
)

_APIM_BACKEND_DURATION = MetricsApiTemplate(
    azure_metric_name="BackendDuration",
    aggregation="Average",
    resource_type=_APIM_TYPE,
)

_CONTAINER_APP_CPU_NANOCORES = MetricsApiTemplate(
    azure_metric_name="UsageNanoCores",
    aggregation="Average",
)

_CONTAINER_APP_MEMORY_PERCENT = MetricsApiTemplate(
    azure_metric_name="MemoryPercentage",
    aggregation="Average",
    interval="PT5M",
)

_CONTAINER_APP_REQUEST_TIMEOUTS = MetricsApiTemplate(
    azure_metric_name="ResiliencyRequestTimeouts",
    aggregation="Total",
    interval="PT5M",
)

_CONTAINER_APP_RESPONSE_TIME_MS = MetricsApiTemplate(
    azure_metric_name="ResponseTime",
    aggregation="Average",
)


def _status_count(
    metric_name: str, resource_type: str, dimension: str, status: str
) -> MetricsApiTemplate:
    return MetricsApiTemplate(
        azure_metric_name=metric_name,
        aggregation="Total",
        resource_type=resource_type,
        dimension_filters=(MetricsApiDimensionFilter(dimension, status),),
        deployment_scope=resource_type == _MODEL_TYPE,
    )


_QUERIES: Mapping[str, MetricsApiTemplate] = MappingProxyType(
    {
        METRIC_MYSQL_CPU_PERCENT: _MYSQL_CPU_PERCENT,
        METRIC_MYSQL_ACTIVE_CONNECTIONS: _MYSQL_ACTIVE_CONNECTIONS,
        METRIC_BACKEND_FIRST_BYTE_MS: _APPGW_BACKEND_FIRST_BYTE,
        METRIC_HEALTHY_HOST_COUNT: _APPGW_HEALTHY_HOST_COUNT,
        METRIC_APIM_BACKEND_LATENCY_MS: _APIM_BACKEND_DURATION,
        METRIC_CONTAINER_APP_CPU_NANOCORES: _CONTAINER_APP_CPU_NANOCORES,
        METRIC_CONTAINER_APP_MEMORY_PERCENT: _CONTAINER_APP_MEMORY_PERCENT,
        METRIC_CONTAINER_APP_REQUEST_TIMEOUTS: _CONTAINER_APP_REQUEST_TIMEOUTS,
        METRIC_SERVICE_REQUEST_DURATION_MS: _CONTAINER_APP_RESPONSE_TIME_MS,
        "gateway.total_time": MetricsApiTemplate(
            "ApplicationGatewayTotalTime", "Average", resource_type=_APPGW_TYPE
        ),
        "gateway.backend.connect_time": MetricsApiTemplate(
            "BackendConnectTime", "Average", resource_type=_APPGW_TYPE
        ),
        "gateway.backend.first_byte_time": _APPGW_BACKEND_FIRST_BYTE,
        "gateway.backend.last_byte_time": MetricsApiTemplate(
            "BackendLastByteResponseTime", "Average", resource_type=_APPGW_TYPE
        ),
        "gateway.backend.healthy_host_count": _APPGW_HEALTHY_HOST_COUNT,
        "gateway.backend.unhealthy_host_count": MetricsApiTemplate(
            "UnhealthyHostCount", "Average", resource_type=_APPGW_TYPE
        ),
        "gateway.response.5xx.count": _status_count(
            "ResponseStatus", _APPGW_TYPE, "HttpStatusGroup", "5xx"
        ),
        "gateway.backend.response.5xx.count": _status_count(
            "BackendResponseStatus", _APPGW_TYPE, "HttpStatusGroup", "5xx"
        ),
        "api_gateway.duration": MetricsApiTemplate("Duration", "Average", resource_type=_APIM_TYPE),
        "api_gateway.backend.duration": _APIM_BACKEND_DURATION,
        "api_gateway.request.count": MetricsApiTemplate(
            "Requests", "Total", resource_type=_APIM_TYPE
        ),
        **{
            f"api_gateway.response.{status}.count": _status_count(
                "Requests", _APIM_TYPE, "GatewayResponseCode", status
            )
            for status in ("429", "500", "503")
        },
        **{
            f"api_gateway.backend.response.{status}.count": _status_count(
                "Requests", _APIM_TYPE, "BackendResponseCode", status
            )
            for status in ("429", "500", "503")
        },
        "model.request.count": MetricsApiTemplate(
            "AzureOpenAIRequests", "Total", resource_type=_MODEL_TYPE, deployment_scope=True
        ),
        **{
            f"model.response.{status}.count": _status_count(
                "AzureOpenAIRequests", _MODEL_TYPE, "StatusCode", status
            )
            for status in ("429", "500", "503")
        },
        "model.time_to_response": MetricsApiTemplate(
            "AzureOpenAITimeToResponse", "Average", resource_type=_MODEL_TYPE, deployment_scope=True
        ),
        "model.time_to_last_byte": MetricsApiTemplate(
            "AzureOpenAITTLTInMS", "Average", resource_type=_MODEL_TYPE, deployment_scope=True
        ),
        "model.token.count": MetricsApiTemplate(
            "TokenTransaction", "Total", resource_type=_MODEL_TYPE, deployment_scope=True
        ),
    }
)


def azure_metrics_api_queries() -> Mapping[str, MetricsApiTemplate]:
    """Return the CSP-neutral ``metric_name`` -> Azure Metrics API
    template map this adapter is authorized to serve.

    Keys are provider metrics referenced by reviewed semantic concepts or
    legacy analyzers. APIM gateway and backend response codes remain distinct
    dimensions; neither identifies a failing policy. Model token counts are
    observed consumption, not a capacity-to-TPM conversion. Templates request
    aggregate series, never an unbounded dimension split.
    """
    return _QUERIES


__all__ = [
    "azure_metrics_api_queries",
]
