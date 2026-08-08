"""Bounded internal liveness and readiness server for the worker process."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Final

_MAX_REQUEST_LINE_BYTES: Final[int] = 2_048
_MAX_STATUS_BODY_BYTES: Final[int] = 16_384

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


def _json_response(status: str, payload: Mapping[str, object]) -> bytes:
    body = json.dumps(dict(payload), separators=(",", ":"), sort_keys=True).encode()
    if len(body) > _MAX_STATUS_BODY_BYTES:
        raise ValueError("worker status response exceeds the bounded payload size")
    return (
        f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
    ).encode() + body


_STATUS_UNAVAILABLE = _json_response("503 Service Unavailable", {"status": "unavailable"})


@dataclass(slots=True)
class RuntimeHealthServer:
    port: int
    readiness: Callable[[], bool] = field(default=lambda: True, repr=False)
    status: Callable[[], Mapping[str, object]] = field(default=dict, repr=False)
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
            line = await reader.readline()
            parts = line.split(b" ", 2) if len(line) <= _MAX_REQUEST_LINE_BYTES else ()
            if len(parts) >= 2 and parts[0] == b"GET" and parts[1] == b"/live":
                response = _OK
            elif len(parts) >= 2 and parts[0] == b"GET" and parts[1] == b"/ready":
                response = _OK if self.readiness() else _NOT_READY
            elif len(parts) >= 2 and parts[0] == b"GET" and parts[1] == b"/status":
                try:
                    response = _json_response("200 OK", self.status())
                except (TypeError, ValueError):
                    response = _STATUS_UNAVAILABLE
            else:
                response = _NOT_FOUND
            writer.write(response)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
