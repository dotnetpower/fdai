from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from fdai.delivery.azure.read_investigation import (
    AzureReadRestConfig,
    AzureReadRestError,
    AzureReadScopeBinding,
    AzureRestReadTransport,
)
from fdai.shared.providers.read_investigation import ReadToolLimits, ResourceSelector
from fdai.shared.providers.workload_identity import IdentityToken

NOW = datetime(2026, 7, 22, tzinfo=UTC)
RESOURCE_ID = (
    "/subscriptions/sub-example/resourceGroups/rg-example/"
    "providers/Microsoft.Compute/virtualMachines/vm-01"
)
NSG_ID = (
    "/subscriptions/sub-example/resourceGroups/rg-example/"
    "providers/Microsoft.Network/networkSecurityGroups/nsg-app"
)
VNET_ID = (
    "/subscriptions/sub-example/resourceGroups/rg-example/"
    "providers/Microsoft.Network/virtualNetworks/vnet-hub"
)
LIMITS = ReadToolLimits(timeout_seconds=10, max_results=8, max_output_bytes=64_000)


class _Identity:
    def __init__(self) -> None:
        self.audiences: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.audiences.append(audience)
        return IdentityToken(
            token="test-token",
            expires_at=NOW + timedelta(hours=1),
            audience=audience,
        )


def _config(*, max_attempts: int = 3) -> AzureReadRestConfig:
    return AzureReadRestConfig(
        scopes=(
            AzureReadScopeBinding(
                "scope:allowed",
                "sub-example",
                ("rg-example",),
                "workspace-example",
            ),
        ),
        resource_type_map=(
            ("Microsoft.Compute/virtualMachines", "compute.vm"),
            ("Microsoft.Network/networkSecurityGroups", "network.nsg"),
            ("Microsoft.Network/virtualNetworks", "network.vnet"),
        ),
        max_attempts=max_attempts,
    )


async def test_rest_transport_executes_only_server_owned_bounded_queries() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer test-token"
        if "Microsoft.ResourceGraph/resources" in request.url.path:
            body = json.loads(request.content)
            assert body["subscriptions"] == ["sub-example"]
            query = body["query"]
            if query.startswith("HealthResources"):
                return httpx.Response(200, json={"data": []})
            if "extend state=" in query:
                return httpx.Response(200, json={"data": [{"state": "PowerState/stopped"}]})
            assert "name =~ 'vm-01'" in query
            assert "resourceGroup in~ ('rg-example')" in query
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": RESOURCE_ID,
                            "name": "vm-01",
                            "type": "Microsoft.Compute/virtualMachines",
                            "resourceGroup": "rg-example",
                        }
                    ]
                },
            )
        if "eventtypes/management/values" in request.url.path:
            assert "resourceUri eq" in request.url.params["$filter"]
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "eventTimestamp": NOW.isoformat(),
                            "status": {"value": "Succeeded"},
                            "operationName": {"value": "deallocate"},
                            "caller": "caller@example.com",
                            "correlationId": "provider-correlation",
                            "claims": {
                                "appid": "application",
                                "http://schemas.microsoft.com/identity/claims/objectidentifier": (
                                    "opaque-object"
                                ),
                            },
                        }
                    ],
                    "nextLink": "https://management.azure.com/next-page",
                },
            )
        if request.url.path.endswith(
            "/providers/Microsoft.ResourceHealth/availabilityStatuses/current"
        ):
            return httpx.Response(
                200,
                json={
                    "properties": {
                        "availabilityState": "Available",
                        "reasonType": "PlatformInitiated",
                        "reportedTime": NOW.isoformat(),
                    }
                },
            )
        assert request.url.path.endswith("/v1/workspaces/workspace-example/query")
        body = json.loads(request.content)
        assert "EventID in (1074, 6006)" in body["query"]
        assert RESOURCE_ID in body["query"]
        return httpx.Response(
            200,
            json={
                "tables": [
                    {
                        "columns": [{"name": "occurred_at"}, {"name": "status"}],
                        "rows": [[NOW.isoformat(), "observed"]],
                    }
                ]
            },
        )

    identity = _Identity()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = AzureRestReadTransport(
            config=_config(),
            identity=identity,
            http_client=client,
            clock=lambda: NOW,
        )
        resources = await transport.resolve_resources(
            ResourceSelector(name="vm-01", scope_ref="scope:allowed"),
            limits=LIMITS,
        )
        assert resources[0]["type"] == "compute.vm"
        state = await transport.get_resource_state(RESOURCE_ID, limits=LIMITS)
        activity = await transport.query_resource_activity(
            RESOURCE_ID, lookback_seconds=3_600, limits=LIMITS
        )
        health = await transport.query_resource_health(
            RESOURCE_ID, lookback_seconds=3_600, limits=LIMITS
        )
        guest = await transport.query_guest_shutdown_events(
            RESOURCE_ID, lookback_seconds=3_600, limits=LIMITS
        )

    assert state[0]["state"] == "stopped"
    assert activity[0]["caller_kind"] == "user"
    assert activity[-1] == {"_truncated": True}
    assert health[0]["health_kind"] == "PlatformInitiated"
    assert guest[0]["status"] == "observed"
    assert identity.audiences.count("https://management.azure.com/.default") == 5
    assert identity.audiences[-1] == "https://api.loganalytics.io/.default"
    assert len(requests) == 6


async def test_scope_mismatch_is_rejected_before_http() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = AzureRestReadTransport(
            config=_config(), identity=_Identity(), http_client=client, clock=lambda: NOW
        )
        with pytest.raises(PermissionError, match="outside"):
            await transport.get_resource_state(
                RESOURCE_ID.replace("sub-example", "other-sub"),
                limits=LIMITS,
            )
        with pytest.raises(PermissionError, match="resource group"):
            await transport.resolve_resources(
                ResourceSelector(
                    name="vm-01",
                    scope_ref="scope:allowed",
                    resource_group="rg-other",
                ),
                limits=LIMITS,
            )
    assert calls == 0


async def test_throttling_honors_retry_after_within_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "4"})
        return httpx.Response(200, json={"data": []})

    async def capture_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(
        "fdai.delivery.azure.read_investigation.rest_transport.asyncio.sleep",
        capture_sleep,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = AzureRestReadTransport(
            config=_config(max_attempts=2),
            identity=_Identity(),
            http_client=client,
            clock=lambda: NOW,
        )
        result = await transport.resolve_resources(
            ResourceSelector(name="vm-01", scope_ref="scope:allowed"),
            limits=LIMITS,
        )

    assert result == []
    assert calls == 2
    assert delays == [4.0]


async def test_resource_health_fallback_honors_lookback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/providers/Microsoft.ResourceGraph/resources"):
            return httpx.Response(200, json={"data": []})
        return httpx.Response(
            200,
            json={
                "properties": {
                    "availabilityState": "Unavailable",
                    "reasonType": "PlatformInitiated",
                    "reportedTime": (NOW - timedelta(minutes=5)).isoformat(),
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = AzureRestReadTransport(
            config=_config(),
            identity=_Identity(),
            http_client=client,
            clock=lambda: NOW,
        )

        health = await transport.query_resource_health(
            RESOURCE_ID,
            lookback_seconds=60,
            limits=LIMITS,
        )

    assert health == ()


async def test_network_queries_project_only_bounded_server_owned_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["api-version"] == "2025-05-01"
        if request.url.path.endswith("/networkSecurityGroups/nsg-app"):
            return httpx.Response(
                200,
                json={
                    "properties": {
                        "networkInterfaces": [{"id": f"{VNET_ID}/networkInterfaces/nic-app"}],
                        "subnets": [{"id": f"{VNET_ID}/subnets/app"}],
                        "securityRules": [
                            {
                                "name": "allow-https",
                                "properties": {
                                    "access": "Allow",
                                    "direction": "Inbound",
                                    "protocol": "Tcp",
                                    "sourceAddressPrefix": "Internet",
                                    "sourceAddressPrefixes": [],
                                    "sourcePortRange": "*",
                                    "sourcePortRanges": [],
                                    "destinationAddressPrefix": "*",
                                    "destinationAddressPrefixes": [],
                                    "destinationPortRange": "443",
                                    "destinationPortRanges": [],
                                    "priority": 200,
                                    "description": "must not leave the transport",
                                },
                            }
                        ],
                        "defaultSecurityRules": [],
                    }
                },
            )
        assert request.url.path.endswith("/virtualNetworks/vnet-hub/virtualNetworkPeerings")
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "name": "hub-to-spoke",
                        "properties": {
                            "peeringState": "Connected",
                            "peeringSyncLevel": "FullyInSync",
                            "remoteVirtualNetwork": {
                                "id": VNET_ID.replace("vnet-hub", "vnet-spoke")
                            },
                            "remoteVirtualNetworkAddressSpace": {
                                "addressPrefixes": ["10.20.0.0/16"]
                            },
                            "allowVirtualNetworkAccess": True,
                            "allowForwardedTraffic": True,
                            "allowGatewayTransit": True,
                            "useRemoteGateways": False,
                        },
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = AzureRestReadTransport(
            config=_config(), identity=_Identity(), http_client=client, clock=lambda: NOW
        )
        rules = await transport.query_network_security(NSG_ID, limits=LIMITS)
        peerings = await transport.query_network_peerings(VNET_ID, limits=LIMITS)

    assert rules == (
        {
            "observed_at": NOW.isoformat(),
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
            "associations": "nic:nic-app,subnet:app",
        },
    )
    assert "description" not in rules[0]
    assert peerings[0]["remote_vnet"] == "vnet-spoke"
    assert peerings[0]["sync_level"] == "FullyInSync"


async def test_throttling_retries_within_cap_and_output_overflow_fails_closed() -> None:
    calls = 0

    def retry_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(retry_handler)) as client:
        transport = AzureRestReadTransport(
            config=_config(max_attempts=2),
            identity=_Identity(),
            http_client=client,
            clock=lambda: NOW,
        )
        assert (
            await transport.resolve_resources(
                ResourceSelector(name="vm-01", scope_ref="scope:allowed"),
                limits=LIMITS,
            )
            == []
        )
    assert calls == 2

    def oversized(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"padding": "x" * 2_000}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(oversized)) as client:
        transport = AzureRestReadTransport(
            config=AzureReadRestConfig(
                scopes=(
                    AzureReadScopeBinding(
                        "scope:allowed",
                        "sub-example",
                        ("rg-example",),
                        "workspace-example",
                    ),
                ),
                resource_type_map=(("Microsoft.Compute/virtualMachines", "compute.vm"),),
                max_attempts=1,
                max_raw_response_bytes=1_024,
            ),
            identity=_Identity(),
            http_client=client,
            clock=lambda: NOW,
        )
        with pytest.raises(AzureReadRestError, match="raw page cap"):
            await transport.resolve_resources(
                ResourceSelector(name="vm-01", scope_ref="scope:allowed"),
                limits=LIMITS,
            )


async def test_activity_lookback_beyond_retention_fails_before_http() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = AzureRestReadTransport(
            config=_config(),
            identity=_Identity(),
            http_client=client,
            clock=lambda: NOW,
        )
        with pytest.raises(AzureReadRestError, match="retention"):
            await transport.query_resource_activity(
                RESOURCE_ID,
                lookback_seconds=91 * 24 * 3_600,
                limits=LIMITS,
            )
    assert calls == 0


async def test_guest_lookback_beyond_retention_fails_before_http() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = AzureRestReadTransport(
            config=_config(),
            identity=_Identity(),
            http_client=client,
            clock=lambda: NOW,
        )
        with pytest.raises(AzureReadRestError, match="guest log lookback.*retention"):
            await transport.query_guest_shutdown_events(
                RESOURCE_ID,
                lookback_seconds=31 * 24 * 3_600,
                limits=LIMITS,
            )
    assert calls == 0
