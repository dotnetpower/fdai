from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from fdai.delivery.azure.read_investigation import (
    AzureOperationsGatewayReadConfig,
    AzureOperationsGatewayReadTransport,
    AzureRow,
)
from fdai.shared.providers.read_investigation import ReadToolLimits, ResourceSelector
from fdai.shared.providers.workload_identity import IdentityToken

_NOW = datetime(2026, 7, 22, tzinfo=UTC)
_LIMITS = ReadToolLimits(timeout_seconds=10, max_results=8, max_output_bytes=64_000)
_NSG_REF = (
    "/subscriptions/sub-example/resourceGroups/rg-example/providers/"
    "Microsoft.Network/networkSecurityGroups/nsg-app"
)


class _Identity:
    def __init__(self) -> None:
        self.audiences: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.audiences.append(audience)
        return IdentityToken(
            token="gateway-token",
            expires_at=_NOW + timedelta(hours=1),
            audience=audience,
        )


class _Delegate:
    transport_id = "rest"

    async def resolve_resources(
        self, selector: ResourceSelector, *, limits: ReadToolLimits
    ) -> Sequence[AzureRow]:
        del selector, limits
        return ()

    async def get_resource_state(
        self, provider_ref: str, *, limits: ReadToolLimits
    ) -> Sequence[AzureRow]:
        del provider_ref, limits
        return ()

    async def query_resource_activity(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        del provider_ref, lookback_seconds, limits
        return ()

    async def query_resource_health(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        del provider_ref, lookback_seconds, limits
        return ()

    async def query_guest_shutdown_events(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        del provider_ref, lookback_seconds, limits
        return ()

    async def query_network_security(
        self, provider_ref: str, *, limits: ReadToolLimits
    ) -> Sequence[AzureRow]:
        del provider_ref, limits
        raise AssertionError("configured gateway MUST own network security reads")

    async def query_network_peerings(
        self, provider_ref: str, *, limits: ReadToolLimits
    ) -> Sequence[AzureRow]:
        del provider_ref, limits
        raise AssertionError("configured gateway MUST own network peering reads")


async def test_gateway_transport_queries_registered_nsg_operation() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "operation_id": "azure.network.nsg.read",
                "status": "succeeded",
                "result": {
                    "name": "nsg-app",
                    "truncated": False,
                    "rules": [
                        {
                            "name": "allow-https",
                            "kind": "custom",
                            "access": "Allow",
                            "direction": "Inbound",
                            "protocol": "Tcp",
                            "priority": 200,
                            "source_address_prefix": "Internet",
                            "source_port_range": "*",
                            "destination_address_prefix": "*",
                            "destination_port_range": "443",
                        }
                    ],
                },
            },
        )

    identity = _Identity()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = AzureOperationsGatewayReadTransport(
            config=AzureOperationsGatewayReadConfig(
                base_url="https://gateway.example.com",
                audience="api-application-id",
                subscription_id="sub-example",
                resource_groups=("rg-example",),
            ),
            delegate=_Delegate(),
            identity=identity,
            http_client=client,
            clock=lambda: _NOW,
        )
        rows = await transport.query_network_security(_NSG_REF, limits=_LIMITS)

    assert requests[0].method == "POST"
    assert requests[0].url.path == "/api/v1/operations/azure.network.nsg.read"
    assert requests[0].headers["Authorization"] == "Bearer gateway-token"
    assert json.loads(requests[0].content) == {
        "resource_group": "rg-example",
        "nsg_name": "nsg-app",
    }
    assert identity.audiences == ["api-application-id"]
    assert rows == (
        {
            "observed_at": _NOW.isoformat(),
            "status": "Allow",
            "rule_name": "allow-https",
            "rule_kind": "custom",
            "direction": "Inbound",
            "protocol": "Tcp",
            "source_prefixes": "Internet",
            "source_ports": "*",
            "destination_prefixes": "*",
            "destination_ports": "443",
            "priority": 200,
        },
    )


async def test_gateway_transport_rejects_scope_before_http() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = AzureOperationsGatewayReadTransport(
            config=AzureOperationsGatewayReadConfig(
                base_url="https://gateway.example.com",
                audience="api-application-id",
                subscription_id="sub-example",
                resource_groups=("rg-example",),
            ),
            delegate=_Delegate(),
            identity=_Identity(),
            http_client=client,
        )
        with pytest.raises(PermissionError, match="outside"):
            await transport.query_network_security(
                _NSG_REF.replace("rg-example", "rg-other"),
                limits=_LIMITS,
            )

    assert calls == 0


async def test_gateway_transport_streams_with_response_size_cap() -> None:
    transport_impl = httpx.MockTransport(
        lambda _request: httpx.Response(200, content=b"x" * 262_145)
    )
    async with httpx.AsyncClient(transport=transport_impl) as client:
        transport = AzureOperationsGatewayReadTransport(
            config=AzureOperationsGatewayReadConfig(
                base_url="https://gateway.example.com",
                audience="api-application-id",
                subscription_id="sub-example",
                resource_groups=("rg-example",),
            ),
            delegate=_Delegate(),
            identity=_Identity(),
            http_client=client,
        )
        with pytest.raises(RuntimeError, match="too large"):
            await transport.query_network_security(_NSG_REF, limits=_LIMITS)
