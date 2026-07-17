"""ASGI middleware used by the console read API."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any


class SecurityHeadersMiddleware:
    """Attach conservative security headers without buffering SSE bodies."""

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self._app = app

    async def __call__(self, scope: Mapping[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        async def send_with_headers(message: Mapping[str, Any]) -> None:
            if message.get("type") != "http.response.start":
                await send(message)
                return

            headers = list(message.get("headers") or [])
            existing_names = {name.lower() for name, _ in headers}

            def add_if_absent(name: bytes, value: bytes) -> None:
                if name.lower() not in existing_names:
                    headers.append((name, value))

            add_if_absent(b"x-content-type-options", b"nosniff")
            add_if_absent(b"x-frame-options", b"DENY")
            add_if_absent(b"referrer-policy", b"no-referrer")
            add_if_absent(b"cache-control", b"no-store")
            add_if_absent(
                b"strict-transport-security",
                b"max-age=31536000; includeSubDomains",
            )
            new_message = dict(message)
            new_message["headers"] = headers
            await send(new_message)

        await self._app(scope, receive, send_with_headers)


__all__ = ["SecurityHeadersMiddleware"]
