"""Metric-provider assembly extracted from ``wire_azure.py`` (G-4).

Contains :func:`attach_metric_provider` - the composition-root helper
that pairs whichever telemetry backends the deploy exposes
(Prometheus, Azure Monitor Metrics REST API, Azure Monitor Logs KQL)
into either a single :class:`MetricProvider` or a
:class:`~fdai.shared.providers.routed_metric.RoutedMetricProvider`
composite.

Kept in its own module so :mod:`fdai.composition.wire_azure` stays
under the per-file LOC ceiling (see
``coding-conventions.instructions.md § General``) and a fork maintainer
can read the full metric-wiring path without scrolling through the
LLM / prompt / tool composition around it.

Public entry is :func:`attach_metric_provider`; every parameter maps
1:1 onto a field on :class:`~fdai.composition.wire_azure.AzureWireOverrides`,
so the module never imports the overrides dataclass and avoids a
circular import.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from ..delivery.azure.metric_logs import MetricKqlTemplate
    from ..delivery.azure.metrics_api import MetricsApiTemplate
    from ..shared.providers.workload_identity import WorkloadIdentity

from ._helpers import Container

_LOGGER = logging.getLogger(__name__)


def attach_metric_provider(
    container: Container,
    *,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    monitor_workspace_id: str | None,
    monitor_queries: Mapping[str, MetricKqlTemplate] | None,
    metrics_api_queries: Mapping[str, MetricsApiTemplate] | None,
    prometheus_base_url: str | None,
    prometheus_queries: Mapping[str, str] | None,
    prometheus_audience: str | None,
) -> Container:
    """Return a container with :attr:`Container.metric_provider` bound
    to whichever backends the caller exposed.

    Three providers can bind, in latency order:

    1. Prometheus (``prometheus_base_url``): AKS-scoped metrics via
       Managed Prom / self-hosted Prom; sub-minute freshness.
    2. Azure Monitor Metrics REST API (piggybacks on
       ``monitor_workspace_id`` since it uses the same identity):
       direct-mapped Azure PaaS metrics; ~1-3 min freshness.
    3. Azure Monitor Logs KQL (``monitor_workspace_id``): fallback for
       computed metrics (rates, deltas, cross-signal fusion) and any
       name Prom / Metrics API do not know; ~2-5 min ingestion floor.

    When >= 2 providers bind they wrap into a
    :class:`~fdai.shared.providers.routed_metric.RoutedMetricProvider`
    in that order so each analyzer query lands on the fastest backend
    that can serve it. When only one binds it is returned directly (no
    wrapper overhead). None -> the caller's container is returned
    unchanged (upstream default ``NoopMetricProvider`` preserved).
    Upstream default query catalogs for each backend come from the
    shipped modules; a fork override (``*_queries`` argument) always
    wins.
    """
    from ..shared.providers.metric import MetricProvider
    from ..shared.providers.routed_metric import MetricRoute, RoutedMetricProvider

    routes: list[MetricRoute] = []
    log_summary: dict[str, object] = {}

    if prometheus_base_url:
        prom_provider, prom_supported, prom_detail = _build_prometheus_route(
            base_url=prometheus_base_url,
            queries=prometheus_queries,
            audience=prometheus_audience,
            identity=identity,
            http_client=http_client,
        )
        routes.append(MetricRoute(provider=prom_provider, supported_metrics=prom_supported))
        log_summary["prometheus"] = prom_detail

    if monitor_workspace_id:
        metrics_provider, metrics_supported, metrics_detail = _build_metrics_api_route(
            queries=metrics_api_queries,
            identity=identity,
            http_client=http_client,
        )
        routes.append(MetricRoute(provider=metrics_provider, supported_metrics=metrics_supported))
        log_summary["azure_monitor_metrics"] = metrics_detail

        aml_provider, aml_supported, aml_detail = _build_aml_route(
            workspace_id=monitor_workspace_id,
            queries=monitor_queries,
            identity=identity,
            http_client=http_client,
        )
        routes.append(MetricRoute(provider=aml_provider, supported_metrics=aml_supported))
        log_summary["azure_monitor_logs"] = aml_detail

    if not routes:
        _LOGGER.info(
            "metric_provider_skipped",
            extra={
                "reason": (
                    "neither monitor_workspace_id nor prometheus_base_url "
                    "supplied - NoopMetricProvider stays"
                )
            },
        )
        return container

    if len(routes) == 1:
        _LOGGER.info(
            "metric_provider_bound_single",
            extra={
                "provider": type(routes[0].provider).__name__,
                "detail": log_summary,
            },
        )
        return replace(container, metric_provider=routes[0].provider)

    routed: MetricProvider = RoutedMetricProvider(routes=routes)
    _LOGGER.info(
        "metric_provider_routed",
        extra={
            "route_count": len(routes),
            "route_order": [type(r.provider).__name__ for r in routes],
            "detail": log_summary,
        },
    )
    return replace(container, metric_provider=routed)


def _build_prometheus_route(
    *,
    base_url: str,
    queries: Mapping[str, str] | None,
    audience: str | None,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
) -> tuple[Any, frozenset[str], dict[str, object]]:
    from ..delivery.prometheus import (
        PrometheusMetricConfig,
        PrometheusMetricProvider,
        aks_managed_prometheus_queries,
    )

    prom_queries = queries or aks_managed_prometheus_queries()
    provider = PrometheusMetricProvider(
        config=PrometheusMetricConfig(
            base_url=base_url,
            queries=prom_queries,
            audience=audience,
        ),
        http_client=http_client,
        identity=identity if audience else None,
    )
    detail: dict[str, object] = {
        "query_count": len(prom_queries),
        "query_source": ("override" if queries is not None else "aks_managed_prometheus_queries"),
    }
    return provider, frozenset(prom_queries.keys()), detail


def _build_metrics_api_route(
    *,
    queries: Mapping[str, MetricsApiTemplate] | None,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
) -> tuple[Any, frozenset[str], dict[str, object]]:
    from ..delivery.azure.metrics_api import (
        AzureMonitorMetricsConfig,
        AzureMonitorMetricsProvider,
    )
    from ..delivery.azure.metrics_api_queries import azure_metrics_api_queries

    templates = queries or azure_metrics_api_queries()
    provider = AzureMonitorMetricsProvider(
        config=AzureMonitorMetricsConfig(templates=templates),
        http_client=http_client,
        identity=identity,
    )
    detail: dict[str, object] = {
        "template_count": len(templates),
        "template_source": ("override" if queries is not None else "azure_metrics_api_queries"),
    }
    return provider, frozenset(templates.keys()), detail


def _build_aml_route(
    *,
    workspace_id: str,
    queries: Mapping[str, MetricKqlTemplate] | None,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
) -> tuple[Any, frozenset[str], dict[str, object]]:
    from ..delivery.azure.demo_queries import default_metric_queries
    from ..delivery.azure.metric_logs import (
        AzureMonitorLogsConfig,
        AzureMonitorLogsMetricProvider,
    )

    aml_queries = queries or default_metric_queries()
    provider = AzureMonitorLogsMetricProvider(
        config=AzureMonitorLogsConfig(workspace_id=workspace_id, queries=aml_queries),
        identity=identity,
        http_client=http_client,
    )
    detail: dict[str, object] = {
        "workspace_id": workspace_id,
        "query_count": len(aml_queries),
        "query_source": ("override" if queries is not None else "default_metric_queries"),
    }
    return provider, frozenset(aml_queries.keys()), detail


__all__ = ["attach_metric_provider"]
