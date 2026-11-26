"""Versioned typed RPC discovery and invocation registry."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol

RPC_SCHEMA_VERSION = "1.0.0"
_METHOD_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{2,127}$")
_MAX_REQUEST_ID_CHARS = 200
_MAX_IDEMPOTENCY_KEY_CHARS = 256


class RpcScope(StrEnum):
    READ = "operator.read"
    WRITE = "operator.write"
    APPROVE = "operator.approve"
    ADMIN = "operator.admin"


@dataclass(frozen=True, slots=True)
class RpcRequest:
    request_id: str
    method: str
    params: Mapping[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None
    schema_version: str = RPC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RPC_SCHEMA_VERSION:
            raise ValueError("unsupported RPC schema_version")
        if not self.request_id or len(self.request_id) > _MAX_REQUEST_ID_CHARS:
            raise ValueError("RPC request_id is empty or over the cap")
        if _METHOD_PATTERN.fullmatch(self.method) is None:
            raise ValueError("RPC method has an invalid name")
        if self.idempotency_key is not None and (
            not self.idempotency_key or len(self.idempotency_key) > _MAX_IDEMPOTENCY_KEY_CHARS
        ):
            raise ValueError("RPC idempotency_key is empty or over the cap")
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))


@dataclass(frozen=True, slots=True)
class RpcResponse:
    request_id: str
    ok: bool
    result: Mapping[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    schema_version: str = RPC_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "ok": self.ok,
            "result": dict(self.result),
            "error": (
                None
                if self.error_code is None
                else {"code": self.error_code, "message": self.error_message}
            ),
        }


RpcHandler = Callable[[Mapping[str, Any]], Awaitable[Mapping[str, Any]]]


@dataclass(frozen=True, slots=True)
class RpcInvocationContext:
    scopes: frozenset[RpcScope]


RpcContextHandler = Callable[
    [Mapping[str, Any], RpcInvocationContext],
    Awaitable[Mapping[str, Any]],
]


@dataclass(frozen=True, slots=True)
class RpcMethod:
    name: str
    description: str
    required_scope: RpcScope
    handler: RpcHandler | None = None
    side_effect: bool = False
    context_handler: RpcContextHandler | None = None

    def __post_init__(self) -> None:
        if _METHOD_PATTERN.fullmatch(self.name) is None:
            raise ValueError("RPC method has an invalid name")
        if not self.description.strip():
            raise ValueError("RPC method description MUST be non-empty")
        if (self.handler is None) == (self.context_handler is None):
            raise ValueError("RPC method MUST define exactly one handler")


class RpcError(RuntimeError):
    """Stable expected error raised by an RPC method implementation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RpcIdempotencyStore(Protocol):
    async def get(self, key: str) -> RpcResponse | None: ...

    async def claim(self, key: str) -> bool: ...

    async def complete(self, key: str, response: RpcResponse) -> None: ...


class InMemoryRpcIdempotencyStore:
    """Process-local claim store with the same ambiguity posture as durable adapters."""

    def __init__(self) -> None:
        self._claimed: set[str] = set()
        self._completed: dict[str, RpcResponse] = {}

    async def get(self, key: str) -> RpcResponse | None:
        return self._completed.get(key)

    async def claim(self, key: str) -> bool:
        if key in self._claimed:
            return False
        self._claimed.add(key)
        return True

    async def complete(self, key: str, response: RpcResponse) -> None:
        self._completed[key] = response


class RpcRegistry:
    """Immutable method registry with scoped discovery and dispatch."""

    __slots__ = ("_idempotency", "_methods")

    def __init__(
        self,
        *,
        methods: Mapping[str, RpcMethod] | None = None,
        idempotency_store: RpcIdempotencyStore | None = None,
    ) -> None:
        self._methods = MappingProxyType(dict(methods or {}))
        self._idempotency = idempotency_store or InMemoryRpcIdempotencyStore()

    def register(self, method: RpcMethod) -> RpcRegistry:
        if method.name in self._methods:
            raise ValueError(f"duplicate RPC method {method.name!r}")
        methods = dict(self._methods)
        methods[method.name] = method
        return RpcRegistry(methods=methods, idempotency_store=self._idempotency)

    def discover(self, scopes: frozenset[RpcScope]) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "name": method.name,
                "description": method.description,
                "required_scope": method.required_scope.value,
                "side_effect": method.side_effect,
                "idempotency_required": method.side_effect,
            }
            for method in sorted(self._methods.values(), key=lambda value: value.name)
            if method.required_scope in scopes
        )

    async def invoke(
        self,
        request: RpcRequest,
        *,
        scopes: frozenset[RpcScope],
    ) -> RpcResponse:
        method = self._methods.get(request.method)
        if method is None:
            return _error(request, "method_not_found", "RPC method is not registered")
        if method.required_scope not in scopes:
            return _error(request, "forbidden", "Caller lacks the required RPC scope")

        claim_key: str | None = None
        if method.side_effect:
            if request.idempotency_key is None:
                return _error(
                    request,
                    "idempotency_required",
                    "Side-effect RPC methods require an idempotency key",
                )
            claim_key = f"{method.name}:{request.idempotency_key}"
            prior = await self._idempotency.get(claim_key)
            if prior is not None:
                return replace_request_id(prior, request.request_id)
            if not await self._idempotency.claim(claim_key):
                return _error(
                    request,
                    "request_in_flight",
                    "An RPC request with this idempotency key is already in flight",
                )

        try:
            if method.context_handler is not None:
                result = await method.context_handler(
                    request.params,
                    RpcInvocationContext(scopes=scopes),
                )
            elif method.handler is not None:
                result = await method.handler(request.params)
            else:
                raise RuntimeError("RPC method has no handler")
        except RpcError as exc:
            response = _error(request, exc.code, str(exc))
        except Exception:
            return _error(request, "internal_error", "RPC method failed")
        else:
            response = RpcResponse(request_id=request.request_id, ok=True, result=result)

        if claim_key is not None:
            await self._idempotency.complete(claim_key, response)
        return response


def replace_request_id(response: RpcResponse, request_id: str) -> RpcResponse:
    return RpcResponse(
        request_id=request_id,
        ok=response.ok,
        result=response.result,
        error_code=response.error_code,
        error_message=response.error_message,
    )


def _error(request: RpcRequest, code: str, message: str) -> RpcResponse:
    return RpcResponse(
        request_id=request.request_id,
        ok=False,
        error_code=code,
        error_message=message,
    )


__all__ = [
    "InMemoryRpcIdempotencyStore",
    "RPC_SCHEMA_VERSION",
    "RpcError",
    "RpcIdempotencyStore",
    "RpcInvocationContext",
    "RpcMethod",
    "RpcRegistry",
    "RpcRequest",
    "RpcResponse",
    "RpcScope",
]
