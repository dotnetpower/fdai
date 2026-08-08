"""Typed external RPC contract for governed FDAI clients."""

from fdai.core.rpc.registry import (
    InMemoryRpcIdempotencyStore,
    RpcError,
    RpcIdempotencyStore,
    RpcInvocationContext,
    RpcMethod,
    RpcRegistry,
    RpcRequest,
    RpcResponse,
    RpcScope,
)
from fdai.core.rpc.skill_discovery import skill_discovery_rpc_methods
from fdai.core.rpc.tool_discovery import tool_discovery_rpc_methods

__all__ = [
    "InMemoryRpcIdempotencyStore",
    "RpcError",
    "RpcIdempotencyStore",
    "RpcInvocationContext",
    "RpcMethod",
    "RpcRegistry",
    "RpcRequest",
    "RpcResponse",
    "RpcScope",
    "skill_discovery_rpc_methods",
    "tool_discovery_rpc_methods",
]
