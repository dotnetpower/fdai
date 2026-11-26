from __future__ import annotations

import asyncio
import socket

from fdai_document_worker_service.health import RuntimeHealthServer


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


async def _request(port: int, path: str) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
    await writer.drain()
    response = await reader.read()
    writer.close()
    await writer.wait_closed()
    return response


async def test_worker_health_distinguishes_liveness_from_readiness() -> None:
    ready = False
    server = RuntimeHealthServer(port=_available_port(), readiness=lambda: ready)
    await server.start()
    try:
        assert (await _request(server.port, "/live")).startswith(b"HTTP/1.1 200")
        assert (await _request(server.port, "/ready")).startswith(b"HTTP/1.1 503")
        ready = True
        assert (await _request(server.port, "/ready")).startswith(b"HTTP/1.1 200")
    finally:
        await server.close()
