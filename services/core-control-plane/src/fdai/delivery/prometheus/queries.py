"""AKS-scoped PromQL templates for the reference analyzer metrics.

These templates are available to an explicitly composed Prometheus route.
They are not enough to bind the inventory-backed analyzer by themselves:
Azure Managed Prometheus supplies a ``cluster`` alias, while the analyzer
requires an exact provider resource reference. A deployment must preserve an
exact ``resource_id`` label before it opts this catalog into analyzer routing.

The aggregation deliberately preserves all labels except CPU and mode, so an
exact deployment-supplied identity label survives the expression.

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
# emits for the analyzer's ``GTE 80.0`` bound. ``without`` preserves
# deployment-supplied exact identity labels.
_NODE_CPU_PERCENT_PROMQL = (
    "100 * (1 - avg without (cpu) (sum without (mode) "
    '(rate(node_cpu_seconds_total{job="node", mode=~"idle|iowait|steal"}[5m]))))'
)


_ANALYZER_QUERIES: Mapping[str, str] = MappingProxyType(
    {
        METRIC_NODE_CPU_PERCENT: _NODE_CPU_PERCENT_PROMQL,
    }
)


def aks_managed_prometheus_queries() -> Mapping[str, str]:
    """Return the CSP-neutral ``metric_name`` -> PromQL map AKS Managed
    Prometheus is authorized to serve.

    A deployment that binds this map must ensure every returned series carries
    an exact ``resource_id`` label matching the inventory provider reference.
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
