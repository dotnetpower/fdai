"""AKS-scoped PromQL templates for the reference analyzer metrics.

Design contract: the "Prom-primary, AML-fallback" arm of the
real-time detection wiring. The 14-metric shipped default (see
:func:`fdai.delivery.azure.demo_queries.default_metric_queries`) covers
every analyzer-referenced metric through Azure Monitor Logs KQL - but
KQL has a 2-5 min ingestion floor even under aggressive polling. AKS
Managed Prometheus scrapes on the order of 15 s and exposes the same
CSP-neutral metric names, so an operator with Managed Prometheus wired
gets **sub-minute** detection for the AKS-scoped metrics; Azure
resources that Prometheus does not observe (App Gateway, MySQL, Azure
OpenAI, APIM) stay on the AML floor.

The map here declares only the metrics AKS Managed Prometheus can
serve; the composition root pairs this map with the AML analyzer map
via :class:`~fdai.shared.providers.routed_metric.RoutedMetricProvider`
so a query for ``node_cpu_percent`` goes to Prometheus while a query
for ``http_5xx_rate`` still lands on AML.

Every query is **author-controlled configuration**, never derived from
untrusted input. Recording rules ship in AKS Managed Prometheus by
default; when a fork disables them the queries here degrade to raw
Prometheus expressions the same fork can override via
``AzureWireOverrides.prometheus_queries``.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from fdai.delivery.azure.demo_queries import METRIC_NODE_CPU_PERCENT

# AKS Managed Prometheus exposes the standard node_exporter +
# kube-state-metrics scrape jobs. ``instance:node_cpu:ratio_rate5m`` is
# a common recording rule (Prometheus mixin, exposed by Managed Prom by
# default); it returns per-node CPU utilization as a ratio in [0, 1] so
# multiplying by 100 gives the same percent scale the AML KQL template
# emits for the analyzer's ``GTE 80.0`` bound.
_NODE_CPU_PERCENT_PROMQL = (
    '100 * (1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])))'
)


_ANALYZER_QUERIES: Mapping[str, str] = MappingProxyType(
    {
        METRIC_NODE_CPU_PERCENT: _NODE_CPU_PERCENT_PROMQL,
    }
)


def aks_managed_prometheus_queries() -> Mapping[str, str]:
    """Return the CSP-neutral ``metric_name`` -> PromQL map AKS Managed
    Prometheus is authorized to serve.

    A fork that adds Prometheus-observable metrics (pod restarts via
    ``kube_pod_container_status_restarts_total``, request errors via
    ``rate(http_requests_total{status=~\"5..\"}[1m])``, ...) copies this
    map and adds its own entries, then passes the result via
    ``AzureWireOverrides.prometheus_queries``. Every key MUST also be a
    key the analyzers pass (see
    :func:`fdai.delivery.azure.demo_queries.sre_demo_analyzer_queries`),
    or the metric adapter will fail-closed on a lookup miss.
    """
    return _ANALYZER_QUERIES


__all__ = [
    "aks_managed_prometheus_queries",
]
