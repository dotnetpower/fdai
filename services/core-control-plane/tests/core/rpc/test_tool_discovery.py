"""Typed RPC runtime tool discovery presentation tests."""

from __future__ import annotations

from fdai.core.conversation import RuntimeToolDiscovery, default_tool_schemas
from fdai.core.rpc import (
    RpcRegistry,
    RpcRequest,
    RpcScope,
    tool_discovery_rpc_methods,
)


def _registry() -> RpcRegistry:
    discovery = RuntimeToolDiscovery(
        schemas=default_tool_schemas(),
        installed_tool_names=frozenset({"query_inventory", "approve_hil"}),
    )
    registry = RpcRegistry()
    for method in tool_discovery_rpc_methods(discovery):
        registry = registry.register(method)
    return registry


async def test_reader_rpc_search_hides_approval_tool() -> None:
    response = await _registry().invoke(
        RpcRequest(request_id="r1", method="tools.search", params={"query": "query"}),
        scopes=frozenset({RpcScope.READ}),
    )

    assert response.ok is True
    assert [item["name"] for item in response.result["tools"]] == ["query_inventory"]


async def test_approver_rpc_describes_metadata_without_invocation_handle() -> None:
    response = await _registry().invoke(
        RpcRequest(
            request_id="r1",
            method="tools.describe",
            params={"tool_name": "approve_hil"},
        ),
        scopes=frozenset({RpcScope.READ, RpcScope.APPROVE}),
    )

    assert response.ok is True
    descriptor = response.result["tool"]
    assert descriptor["side_effect_class"] == "approve"
    assert "handler" not in descriptor
    assert "call" not in descriptor
