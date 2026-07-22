"""Local Azure CLI wiring for bounded read investigations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from fdai.core.read_investigation import InvestigationExecutionPolicy, ReadInvestigationService
from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.azure.read_investigation import (
    AzureOperationsGatewayReadConfig,
    AzureOperationsGatewayReadTransport,
    AzureReadRestConfig,
    AzureReadScopeBinding,
    AzureRestReadInvestigationAdapter,
    AzureRestReadTransport,
)
from fdai.delivery.azure.read_investigation.transport import AzureReadTransport
from fdai.delivery.azure.subscription_health import (
    AzureSubscriptionHealthConfig,
    AzureSubscriptionHealthProvider,
)
from fdai.delivery.persistence import StateStoreReadLatencyProfileStore
from fdai.delivery.read_api.routes.read_investigation_responder import (
    HeimdallReadInvestigationChatDelegate,
    HeimdallReadInvestigationResponder,
)


@dataclass(frozen=True, slots=True)
class LocalReadInvestigationWiring:
    chat_delegate: HeimdallReadInvestigationChatDelegate
    subscription_health_provider: AzureSubscriptionHealthProvider
    read_transport: AzureReadTransport
    http_client: httpx.AsyncClient

    async def close(self) -> None:
        await self.http_client.aclose()


def build_local_read_investigation(
    *,
    state_store: Any,
    environ: Mapping[str, str],
) -> LocalReadInvestigationWiring | None:
    subscription_id = environ.get("FDAI_AZURE_READER_SUBSCRIPTION_ID", "").strip()
    resource_groups = tuple(
        dict.fromkeys(
            value.strip()
            for value in environ.get("FDAI_AZURE_READER_RESOURCE_GROUPS", "").split(",")
            if value.strip()
        )
    )
    if not subscription_id or not resource_groups:
        return None
    scope_ref = "azure-reader-local"
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=35.0, write=10.0, pool=5.0)
    )
    identity = AsyncAzureCliWorkloadIdentity()
    direct_transport = AzureRestReadTransport(
        config=AzureReadRestConfig(
            scopes=(
                AzureReadScopeBinding(
                    scope_ref=scope_ref,
                    subscription_id=subscription_id,
                    resource_groups=resource_groups,
                    workspace_id=environ.get("FDAI_MONITOR_WORKSPACE_ID", "").strip() or None,
                ),
            ),
            resource_type_map=(
                ("Microsoft.Compute/virtualMachines", "compute.vm"),
                ("Microsoft.Network/networkSecurityGroups", "network.nsg"),
                ("Microsoft.Network/virtualNetworks", "network.vnet"),
            ),
        ),
        identity=identity,
        http_client=http_client,
    )
    gateway_url = environ.get("FDAI_DEV_OPERATIONS_GATEWAY_URL", "").strip()
    gateway_audience = environ.get("FDAI_DEV_OPERATIONS_GATEWAY_AUDIENCE", "").strip()
    if bool(gateway_url) != bool(gateway_audience):
        raise ValueError("operations gateway URL and audience MUST be configured together")
    transport: AzureReadTransport = direct_transport
    if gateway_url:
        transport = AzureOperationsGatewayReadTransport(
            config=AzureOperationsGatewayReadConfig(
                base_url=gateway_url,
                audience=gateway_audience,
                subscription_id=subscription_id,
                resource_groups=resource_groups,
            ),
            delegate=direct_transport,
            identity=identity,
            http_client=http_client,
        )
    latency_store = StateStoreReadLatencyProfileStore(store=state_store)
    service = ReadInvestigationService(
        AzureRestReadInvestigationAdapter(transport),
        latency_store=latency_store,
    )
    return LocalReadInvestigationWiring(
        chat_delegate=HeimdallReadInvestigationChatDelegate(
            responder=HeimdallReadInvestigationResponder(
                service=service,
                latency_store=latency_store,
                scope_ref=scope_ref,
                policy=InvestigationExecutionPolicy(
                    direct_max_ms=20_000,
                    streamed_max_ms=30_000,
                    detach_on_multi_source=False,
                ),
            )
        ),
        subscription_health_provider=AzureSubscriptionHealthProvider(
            config=AzureSubscriptionHealthConfig(
                subscription_id=subscription_id,
                resource_groups=resource_groups,
            ),
            identity=identity,
            http_client=http_client,
        ),
        read_transport=transport,
        http_client=http_client,
    )


__all__ = ["LocalReadInvestigationWiring", "build_local_read_investigation"]
