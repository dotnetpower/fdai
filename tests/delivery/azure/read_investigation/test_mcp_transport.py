from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from mcp.types import TextContent

from fdai.delivery.azure.read_investigation import AzureMcpReadTransport, AzureRow
from fdai.delivery.mcp import ManagedMcpClient, ManagedMcpClientConfig, McpCallResult
from fdai.shared.providers.read_investigation import ReadToolLimits, ResourceSelector

NOW = datetime(2026, 8, 1, tzinfo=UTC)
RESOURCE_ID = (
    "/subscriptions/example/resourceGroups/rg-example/"
    "providers/Microsoft.Compute/virtualMachines/vm-01"
)
LIMITS = ReadToolLimits(timeout_seconds=2, max_results=8, max_output_bytes=64_000)


class _McpSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, object]]] = []
        self.results: dict[str, McpCallResult] = {}
        self.fail = False

    async def list_tools(self) -> frozenset[str]:
        return frozenset({"compute", "monitor", "resourcehealth"})

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, object],
        *,
        timeout_seconds: float,
    ) -> McpCallResult:
        del timeout_seconds
        self.calls.append((name, arguments))
        if self.fail:
            raise RuntimeError("synthetic MCP failure")
        return self.results[name]

    async def close(self) -> None:
        return None


class _Fallback:
    transport_id = "rest"

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.health_lookbacks: list[int] = []

    async def resolve_resources(
        self, selector: ResourceSelector, *, limits: ReadToolLimits
    ) -> Sequence[AzureRow]:
        del selector, limits
        self.calls.append("resolve")
        return []

    async def get_resource_state(
        self, provider_ref: str, *, limits: ReadToolLimits
    ) -> Sequence[AzureRow]:
        del provider_ref, limits
        self.calls.append("state")
        return [{"observed_at": NOW.isoformat(), "status": "ok", "state": "fallback"}]

    async def query_resource_activity(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        del provider_ref, lookback_seconds, limits
        self.calls.append("activity")
        return []

    async def query_resource_health(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        del provider_ref, limits
        self.calls.append("health")
        self.health_lookbacks.append(lookback_seconds)
        return []

    async def query_guest_shutdown_events(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        del provider_ref, lookback_seconds, limits
        self.calls.append("guest")
        return []

    async def query_network_security(
        self, provider_ref: str, *, limits: ReadToolLimits
    ) -> Sequence[AzureRow]:
        del provider_ref, limits
        self.calls.append("nsg")
        return []

    async def query_network_peerings(
        self, provider_ref: str, *, limits: ReadToolLimits
    ) -> Sequence[AzureRow]:
        del provider_ref, limits
        self.calls.append("peering")
        return []


def _transport() -> tuple[AzureMcpReadTransport, ManagedMcpClient, _McpSession, _Fallback]:
    session = _McpSession()
    fallback = _Fallback()
    client = ManagedMcpClient(
        session=session,
        config=ManagedMcpClientConfig(
            allowed_tools=frozenset({"compute", "monitor", "resourcehealth"}),
            startup_timeout_seconds=0.2,
            failure_threshold=1,
        ),
    )
    return (
        AzureMcpReadTransport(client=client, fallback=fallback, clock=lambda: NOW),
        client,
        session,
        fallback,
    )


async def test_unavailable_mcp_skips_network_and_uses_fallback() -> None:
    transport, _client, session, fallback = _transport()

    rows = await transport.get_resource_state(RESOURCE_ID, limits=LIMITS)

    assert rows[0]["state"] == "fallback"
    assert session.calls == []
    assert fallback.calls == ["state"]


async def test_vm_state_uses_exact_namespace_command() -> None:
    transport, client, session, fallback = _transport()
    session.results["compute"] = McpCallResult(
        structured_content={"results": {"statuses": [{"code": "PowerState/deallocated"}]}}
    )
    assert await client.probe() is True

    rows = await transport.get_resource_state(RESOURCE_ID, limits=LIMITS)

    assert rows[0]["state"] == "deallocated"
    assert fallback.calls == []
    tool, arguments = session.calls[0]
    assert tool == "compute"
    assert arguments["command"] == "compute_vm_get"
    assert arguments["parameters"] == {
        "resource-group": "rg-example",
        "vm-name": "vm-01",
        "instance-view": True,
    }


async def test_activity_text_result_is_normalized() -> None:
    transport, client, session, fallback = _transport()
    payload = {
        "status": 200,
        "results": {
            "value": [
                {
                    "eventTimestamp": NOW.isoformat(),
                    "operationName": {
                        "value": "Microsoft.Compute/virtualMachines/deallocate/action"
                    },
                    "status": {"localizedValue": "Succeeded"},
                    "caller": "opaque@example.com",
                    "correlationId": "correlation-one",
                }
            ]
        },
    }
    session.results["monitor"] = McpCallResult(
        structured_content=None,
        content=(TextContent(type="text", text=json.dumps(payload)),),
    )
    assert await client.probe() is True

    rows = await transport.query_resource_activity(
        RESOURCE_ID, lookback_seconds=3_601, limits=LIMITS
    )

    assert rows[0]["status"] == "Succeeded"
    assert rows[0]["caller"] == "opaque@example.com"
    assert fallback.calls == []
    assert session.calls[0][1]["parameters"] == {"resource-id": RESOURCE_ID, "hours": 2}


async def test_malformed_mcp_result_falls_back_and_opens_circuit() -> None:
    transport, client, session, fallback = _transport()
    session.results["compute"] = McpCallResult(structured_content={"results": {}})
    assert await client.probe() is True

    first = await transport.get_resource_state(RESOURCE_ID, limits=LIMITS)
    second = await transport.get_resource_state(RESOURCE_ID, limits=LIMITS)

    assert first[0]["state"] == second[0]["state"] == "fallback"
    assert len(session.calls) == 1
    assert fallback.calls == ["state", "state"]


async def test_health_fallback_preserves_original_lookback() -> None:
    transport, client, session, fallback = _transport()
    session.results["resourcehealth"] = McpCallResult(structured_content={"results": {}})
    assert await client.probe() is True

    await transport.query_resource_health(RESOURCE_ID, lookback_seconds=7_200, limits=LIMITS)

    assert fallback.health_lookbacks == [7_200]


async def test_output_cap_counts_content_when_structured_result_exists() -> None:
    transport, client, session, fallback = _transport()
    session.results["compute"] = McpCallResult(
        structured_content={"results": {"powerState": "running"}},
        content=(TextContent(type="text", text="x" * 70_000),),
    )
    assert await client.probe() is True

    rows = await transport.get_resource_state(RESOURCE_ID, limits=LIMITS)

    assert rows[0]["state"] == "fallback"
    assert fallback.calls == ["state"]


async def test_unmapped_sources_always_use_existing_transport() -> None:
    transport, client, session, fallback = _transport()
    assert await client.probe() is True

    await transport.query_guest_shutdown_events(RESOURCE_ID, lookback_seconds=60, limits=LIMITS)
    await transport.query_network_security(RESOURCE_ID, limits=LIMITS)
    await transport.query_network_peerings(RESOURCE_ID, limits=LIMITS)

    assert session.calls == []
    assert fallback.calls == ["guest", "nsg", "peering"]
