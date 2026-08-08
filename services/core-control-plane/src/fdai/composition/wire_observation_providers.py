"""Azure log and trace provider composition for RCA evidence."""

from __future__ import annotations

from dataclasses import replace

import httpx

from fdai.composition._helpers import Container
from fdai.delivery.azure.log_query import (
    AzureLogAnalyticsQueryConfig,
    AzureLogAnalyticsQueryProvider,
)
from fdai.delivery.azure.telemetry_query import (
    AzureLogAnalyticsRcaLogProvider,
    AzureLogAnalyticsTraceProvider,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity


def attach_observation_providers(
    container: Container,
    *,
    workspace_id: str | None,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
) -> Container:
    """Bind typed RCA log and trace providers when a workspace is configured."""

    if not workspace_id:
        return container
    query_provider = AzureLogAnalyticsQueryProvider(
        config=AzureLogAnalyticsQueryConfig(workspace_id=workspace_id),
        identity=identity,
        http_client=http_client,
    )
    return replace(
        container,
        log_query_provider=AzureLogAnalyticsRcaLogProvider(query_provider),
        trace_query_provider=AzureLogAnalyticsTraceProvider(query_provider),
    )


__all__ = ["attach_observation_providers"]
