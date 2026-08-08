"""Typed RPC scope, discovery, idempotency, and error tests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.rpc import (
    RpcError,
    RpcInvocationContext,
    RpcMethod,
    RpcRegistry,
    RpcRequest,
    RpcScope,
)


class _Handler:
    def __init__(self, *, raises: Exception | None = None) -> None:
        self.calls = 0
        self.raises = raises

    async def __call__(self, params: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return {"echo": params.get("value")}


def _registry(handler: _Handler, *, side_effect: bool = False) -> RpcRegistry:
    return RpcRegistry().register(
        RpcMethod(
            name="inventory.query" if not side_effect else "workflow.request",
            description="Test method.",
            required_scope=RpcScope.READ if not side_effect else RpcScope.WRITE,
            side_effect=side_effect,
            handler=handler,
        )
    )


def test_discovery_returns_only_scope_eligible_methods() -> None:
    read = _Handler()
    write = _Handler()
    registry = _registry(read).register(
        RpcMethod(
            name="workflow.request",
            description="Request workflow.",
            required_scope=RpcScope.WRITE,
            side_effect=True,
            handler=write,
        )
    )

    discovered = registry.discover(frozenset({RpcScope.READ}))

    assert [method["name"] for method in discovered] == ["inventory.query"]


async def test_scope_is_checked_before_handler() -> None:
    handler = _Handler()
    response = await _registry(handler).invoke(
        RpcRequest(request_id="r1", method="inventory.query"),
        scopes=frozenset(),
    )

    assert response.error_code == "forbidden"
    assert handler.calls == 0


async def test_side_effect_requires_idempotency_key() -> None:
    handler = _Handler()
    response = await _registry(handler, side_effect=True).invoke(
        RpcRequest(request_id="r1", method="workflow.request"),
        scopes=frozenset({RpcScope.WRITE}),
    )
    assert response.error_code == "idempotency_required"
    assert handler.calls == 0


async def test_completed_idempotent_request_replays_response_without_handler() -> None:
    handler = _Handler()
    registry = _registry(handler, side_effect=True)
    first = await registry.invoke(
        RpcRequest(
            request_id="r1",
            method="workflow.request",
            params={"value": 1},
            idempotency_key="key-1",
        ),
        scopes=frozenset({RpcScope.WRITE}),
    )
    second = await registry.invoke(
        RpcRequest(
            request_id="r2",
            method="workflow.request",
            params={"value": 2},
            idempotency_key="key-1",
        ),
        scopes=frozenset({RpcScope.WRITE}),
    )

    assert first.ok is True and second.ok is True
    assert second.request_id == "r2"
    assert second.result == {"echo": 1}
    assert handler.calls == 1


async def test_unexpected_failure_is_redacted_and_claim_stays_ambiguous() -> None:
    handler = _Handler(raises=RuntimeError("secret internal detail"))
    registry = _registry(handler, side_effect=True)
    request = RpcRequest(
        request_id="r1",
        method="workflow.request",
        idempotency_key="key-1",
    )

    first = await registry.invoke(request, scopes=frozenset({RpcScope.WRITE}))
    second = await registry.invoke(request, scopes=frozenset({RpcScope.WRITE}))

    assert first.error_code == "internal_error"
    assert "secret" not in str(first.to_dict())
    assert second.error_code == "request_in_flight"
    assert handler.calls == 1


async def test_expected_method_error_is_stable_and_idempotent() -> None:
    handler = _Handler(raises=RpcError("invalid_state", "Workflow state is invalid"))
    registry = _registry(handler, side_effect=True)
    request = RpcRequest(
        request_id="r1",
        method="workflow.request",
        idempotency_key="key-1",
    )

    first = await registry.invoke(request, scopes=frozenset({RpcScope.WRITE}))
    second = await registry.invoke(request, scopes=frozenset({RpcScope.WRITE}))

    assert first.error_code == "invalid_state"
    assert second.error_code == "invalid_state"
    assert handler.calls == 1


async def test_unknown_method_returns_stable_error() -> None:
    response = await RpcRegistry().invoke(
        RpcRequest(request_id="r1", method="unknown.method"),
        scopes=frozenset({RpcScope.ADMIN}),
    )
    assert response.error_code == "method_not_found"


async def test_context_handler_receives_server_authorized_scopes() -> None:
    captured: frozenset[RpcScope] = frozenset()

    async def handler(
        params: Mapping[str, Any],
        context: RpcInvocationContext,
    ) -> Mapping[str, Any]:
        nonlocal captured
        captured = context.scopes
        return {"query": params.get("query")}

    registry = RpcRegistry().register(
        RpcMethod(
            name="tools.search",
            description="Search visible tools.",
            required_scope=RpcScope.READ,
            context_handler=handler,
        )
    )
    response = await registry.invoke(
        RpcRequest(request_id="r1", method="tools.search", params={"query": "audit"}),
        scopes=frozenset({RpcScope.READ}),
    )

    assert response.ok is True
    assert captured == frozenset({RpcScope.READ})
