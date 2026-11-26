"""ASGI middleware shared by the Operator HTTP surfaces."""

from __future__ import annotations

import ipaddress

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SecurityHeadersMiddleware:
    """Add non-cacheable JSON safety headers to every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", ()))
                headers.extend(
                    (
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                    )
                )
                message["headers"] = headers
            await send(message)

        await self._app(scope, receive, send_with_headers)


class LoopbackOnlyMiddleware:
    """Reject non-loopback traffic when local CLI authentication is active."""

    def __init__(self, app: ASGIApp, allowed_origins: tuple[str, ...]) -> None:
        self._app = app
        self._allowed_origins = frozenset(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            if not _is_loopback_client(scope.get("client")):
                response = _error(403, "local Azure CLI authentication requires a loopback client")
                await response(scope, receive, send)
                return
            origin = _header_value(scope, b"origin")
            if origin is not None and origin not in self._allowed_origins:
                response = _error(403, "local Azure CLI authentication rejected the request origin")
                await response(scope, receive, send)
                return
        await self._app(scope, receive, send)


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": {"status": status, "message": message}}, status_code=status)


def _is_loopback_client(client: object) -> bool:
    if not isinstance(client, tuple) or not client or not isinstance(client[0], str):
        return False
    try:
        return ipaddress.ip_address(client[0]).is_loopback
    except ValueError:
        return False


def _header_value(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", ()):
        if key.lower() == name and isinstance(value, bytes):
            return value.decode("latin-1")
    return None


__all__ = ["LoopbackOnlyMiddleware", "SecurityHeadersMiddleware"]
