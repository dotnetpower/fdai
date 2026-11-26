"""Azure RCA observation provider composition."""

from __future__ import annotations

from datetime import datetime

import httpx
from fdai.composition import default_container
from fdai.composition.wire_observation_providers import (
    attach_observation_providers,
    attach_telemetry_workspace_resolver,
)
from fdai.delivery.azure.telemetry_query import (
    AzureLogAnalyticsRcaLogProvider,
    AzureLogAnalyticsTraceProvider,
)
from fdai.delivery.azure.telemetry_workspace import AzureTelemetryWorkspaceResolution
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity


class _WorkspaceResolver:
    async def resolve(
        self,
        resource_ref: str,
        *,
        at: datetime,
    ) -> AzureTelemetryWorkspaceResolution:
        raise AssertionError(f"unexpected resolution for {resource_ref} at {at}")


def test_workspace_resolver_attaches_only_to_azure_observation_providers(app_config) -> None:
    container = default_container(app_config)
    identity = StaticWorkloadIdentity(audience="https://api.loganalytics.io/.default")
    client = httpx.AsyncClient()
    observed = attach_observation_providers(
        container,
        workspace_id="workspace-example",
        identity=identity,
        http_client=client,
    )

    routed = attach_telemetry_workspace_resolver(
        observed,
        resolver=_WorkspaceResolver(),
    )

    assert isinstance(routed.log_query_provider, AzureLogAnalyticsRcaLogProvider)
    assert isinstance(routed.trace_query_provider, AzureLogAnalyticsTraceProvider)
    assert routed.log_query_provider is not observed.log_query_provider
    assert routed.trace_query_provider is not observed.trace_query_provider


def test_workspace_resolver_preserves_default_noop_providers(app_config) -> None:
    container = default_container(app_config)

    routed = attach_telemetry_workspace_resolver(
        container,
        resolver=_WorkspaceResolver(),
    )

    assert routed.log_query_provider is container.log_query_provider
    assert routed.trace_query_provider is container.trace_query_provider
