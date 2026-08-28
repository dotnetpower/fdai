"""Azure metric and observation provider composition."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import httpx

from ..shared.providers.workload_identity import WorkloadIdentity
from ._helpers import Container
from .wire_metric_provider import attach_metric_provider
from .wire_observation_providers import attach_observation_providers

if TYPE_CHECKING:
    from ..delivery.azure.metric_logs import MetricKqlTemplate


def attach_azure_observability(
    container: Container,
    *,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    workspace_id: str | None,
    monitor_queries: Mapping[str, MetricKqlTemplate] | None,
    metrics_api_queries: Mapping[str, Any] | None,
    prometheus_base_url: str | None,
    prometheus_queries: Mapping[str, str] | None,
    prometheus_audience: str | None,
) -> Container:
    """Attach routed metrics first, then observation providers over that container."""

    with_metrics = attach_metric_provider(
        container,
        identity=identity,
        http_client=http_client,
        monitor_workspace_id=workspace_id,
        monitor_queries=monitor_queries,
        metrics_api_queries=metrics_api_queries,
        prometheus_base_url=prometheus_base_url,
        prometheus_queries=prometheus_queries,
        prometheus_audience=prometheus_audience,
    )
    return attach_observation_providers(
        with_metrics,
        workspace_id=workspace_id,
        identity=identity,
        http_client=http_client,
    )


__all__ = ["attach_azure_observability"]
