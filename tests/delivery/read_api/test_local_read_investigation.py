from __future__ import annotations

from fdai.delivery.azure.read_investigation import AzureOperationsGatewayReadTransport
from fdai.delivery.read_api.dev.read_investigation import build_local_read_investigation
from fdai.shared.providers.testing.state_store import InMemoryStateStore


async def test_local_read_investigation_requires_server_owned_scope() -> None:
    assert build_local_read_investigation(state_store=InMemoryStateStore(), environ={}) is None


async def test_local_read_investigation_builds_network_delegate() -> None:
    wiring = build_local_read_investigation(
        state_store=InMemoryStateStore(),
        environ={
            "FDAI_AZURE_READER_SUBSCRIPTION_ID": "sub-example",
            "FDAI_AZURE_READER_RESOURCE_GROUPS": "rg-example",
        },
    )
    assert wiring is not None
    try:
        assert wiring.chat_delegate is not None
        assert wiring.subscription_health_provider is not None
    finally:
        await wiring.close()


async def test_local_read_investigation_binds_configured_operations_gateway() -> None:
    wiring = build_local_read_investigation(
        state_store=InMemoryStateStore(),
        environ={
            "FDAI_AZURE_READER_SUBSCRIPTION_ID": "sub-example",
            "FDAI_AZURE_READER_RESOURCE_GROUPS": "rg-example",
            "FDAI_DEV_OPERATIONS_GATEWAY_URL": "https://gateway.example.com",
            "FDAI_DEV_OPERATIONS_GATEWAY_AUDIENCE": "api-application-id",
        },
    )
    assert wiring is not None
    try:
        assert isinstance(wiring.read_transport, AzureOperationsGatewayReadTransport)
    finally:
        await wiring.close()
