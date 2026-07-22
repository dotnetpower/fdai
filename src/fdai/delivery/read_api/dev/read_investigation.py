"""Local Azure CLI wiring for bounded read investigations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from fdai.core.read_investigation import InvestigationExecutionPolicy, ReadInvestigationService
from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.azure.read_investigation import (
    AzureReadRestConfig,
    AzureReadScopeBinding,
    AzureRestReadInvestigationAdapter,
    AzureRestReadTransport,
)
from fdai.delivery.persistence import StateStoreReadLatencyProfileStore
from fdai.delivery.read_api.routes.read_investigation_responder import (
    HeimdallReadInvestigationChatDelegate,
    HeimdallReadInvestigationResponder,
)


@dataclass(frozen=True, slots=True)
class LocalReadInvestigationWiring:
    chat_delegate: HeimdallReadInvestigationChatDelegate
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
    transport = AzureRestReadTransport(
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
        identity=AsyncAzureCliWorkloadIdentity(),
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
                ),
            )
        ),
        http_client=http_client,
    )


__all__ = ["LocalReadInvestigationWiring", "build_local_read_investigation"]
