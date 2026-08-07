"""Bounded internal liveness and readiness server for the worker process."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

_OK = (
    b"HTTP/1.1 200 OK\r\n"
    b"Content-Type: application/json\r\n"
    b"Content-Length: 15\r\nConnection: close\r\n\r\n"
    b'{"status":"ok"}'
)
_NOT_READY = (
    b"HTTP/1.1 503 Service Unavailable\r\n"
    b"Content-Type: application/json\r\n"
    b"Content-Length: 24\r\nConnection: close\r\n\r\n"
    b'{"status":"not-ready"}'
)
_NOT_FOUND = (
    b"HTTP/1.1 404 Not Found\r\n"
    b"Content-Type: application/json\r\n"
    b"Content-Length: 22\r\nConnection: close\r\n\r\n"
    b'{"status":"not-found"}'
)


@dataclass(slots=True)
class RuntimeHealthServer:
    port: int
    readiness: Callable[[], bool] = field(default=lambda: True, repr=False)
    _server: asyncio.Server | None = field(default=None, init=False, repr=False)

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "0.0.0.0", self.port)  # noqa: S104

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            parts = (await reader.readline()).split(b" ", 2)
            if len(parts) >= 2 and parts[0] == b"GET" and parts[1] == b"/live":
                response = _OK
            elif len(parts) >= 2 and parts[0] == b"GET" and parts[1] == b"/ready":
                response = _OK if self.readiness() else _NOT_READY
            else:
                response = _NOT_FOUND
            writer.write(response)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
