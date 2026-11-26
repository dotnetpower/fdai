"""Typed read-only RPC projection for runtime tool discovery."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.conversation import (
    Principal,
    Role,
    RuntimeToolDiscovery,
    ToolDiscoveryError,
)
from fdai.core.rpc.registry import (
    RpcError,
    RpcInvocationContext,
    RpcMethod,
    RpcScope,
)


def tool_discovery_rpc_methods(discovery: RuntimeToolDiscovery) -> tuple[RpcMethod, ...]:
    async def search(
        params: Mapping[str, Any],
        context: RpcInvocationContext,
    ) -> Mapping[str, Any]:
        query = params.get("query")
        limit = params.get("limit", 20)
        if not isinstance(query, str) or not query.strip():
            raise RpcError("invalid_params", "tools.search query MUST be non-empty")
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise RpcError("invalid_params", "tools.search limit MUST be an integer")
        try:
            descriptors = discovery.search(
                query,
                principal=_principal(context),
                limit=limit,
            )
        except ValueError as exc:
            raise RpcError("invalid_params", str(exc)) from exc
        return {"tools": [descriptor.to_dict() for descriptor in descriptors]}

    async def describe(
        params: Mapping[str, Any],
        context: RpcInvocationContext,
    ) -> Mapping[str, Any]:
        tool_name = params.get("tool_name")
        if not isinstance(tool_name, str) or not tool_name:
            raise RpcError("invalid_params", "tools.describe tool_name MUST be non-empty")
        try:
            descriptor = discovery.describe(tool_name, principal=_principal(context))
        except ToolDiscoveryError as exc:
            raise RpcError("tool_unavailable", str(exc)) from exc
        return {"tool": descriptor.to_dict()}

    return (
        RpcMethod(
            name="tools.search",
            description="Search installed tools visible to the caller.",
            required_scope=RpcScope.READ,
            context_handler=search,
        ),
        RpcMethod(
            name="tools.describe",
            description="Describe one installed tool without invoking it.",
            required_scope=RpcScope.READ,
            context_handler=describe,
        ),
    )


def _principal(context: RpcInvocationContext) -> Principal:
    if RpcScope.ADMIN in context.scopes:
        role = Role.OWNER
    elif RpcScope.APPROVE in context.scopes:
        role = Role.APPROVER
    elif RpcScope.WRITE in context.scopes:
        role = Role.CONTRIBUTOR
    else:
        role = Role.READER
    return Principal(id="rpc-caller", role=role)


__all__ = ["tool_discovery_rpc_methods"]
