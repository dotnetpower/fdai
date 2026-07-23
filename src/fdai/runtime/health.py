"""Minimal HTTP health server for the headless control-plane process."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

_MAX_REQUEST_LINE_BYTES: Final[int] = 2_048
_RESPONSE_OK: Final[bytes] = (
    b"HTTP/1.1 200 OK\r\n"
    b"Content-Type: application/json\r\n"
    b"Content-Length: 15\r\n"
    b"Connection: close\r\n\r\n"
    b'{"status":"ok"}'
)
_RESPONSE_NOT_FOUND: Final[bytes] = (
    b"HTTP/1.1 404 Not Found\r\n"
    b"Content-Type: application/json\r\n"
    b"Content-Length: 22\r\n"
    b"Connection: close\r\n\r\n"
    b'{"status":"not-found"}'
)
_RESPONSE_NOT_READY: Final[bytes] = (
    b"HTTP/1.1 503 Service Unavailable\r\n"
    b"Content-Type: application/json\r\n"
    b"Content-Length: 24\r\n"
    b"Connection: close\r\n\r\n"
    b'{"status":"not-ready"}'
)


@dataclass(slots=True)
class RuntimeHealthServer:
    """Serve bounded liveness/readiness responses after runtime wiring succeeds."""

    port: int
    host: str = "0.0.0.0"  # noqa: S104 - Container Apps probes connect through the pod IP
    readiness: Callable[[], bool] = field(default=lambda: True, repr=False)
    _server: asyncio.Server | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not 1 <= self.port <= 65_535:
            raise ValueError("health port MUST be between 1 and 65535")

    async def start(self) -> None:
        if self._server is not None:
            return
        self._server = await asyncio.start_server(self._handle, self.host, self.port)

    async def close(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def _handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            line = await reader.readline()
            if len(line) > _MAX_REQUEST_LINE_BYTES:
                response = _RESPONSE_NOT_FOUND
            else:
                parts = line.split(b" ", 2)
                is_get = len(parts) >= 2 and parts[0] == b"GET"
                if is_get and parts[1] == b"/live":
                    response = _RESPONSE_OK
                elif is_get and parts[1] == b"/ready":
                    response = _RESPONSE_OK if self.readiness() else _RESPONSE_NOT_READY
                else:
                    response = _RESPONSE_NOT_FOUND
            writer.write(response)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()


__all__ = ["RuntimeHealthServer"]
