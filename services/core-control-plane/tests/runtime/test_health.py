"""Socket-level tests for the headless runtime health server."""

from __future__ import annotations

import asyncio

from fdai.runtime.health import RuntimeHealthServer


async def _request(port: int, path: str) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
    await writer.drain()
    response = await reader.read()
    writer.close()
    await writer.wait_closed()
    return response


async def test_health_server_serves_live_and_ready_after_start() -> None:
    server = RuntimeHealthServer(port=1, host="127.0.0.1")
    server._server = await asyncio.start_server(server._handle, server.host, 0)
    socket = server._server.sockets[0]
    port = int(socket.getsockname()[1])
    try:
        live = await _request(port, "/live")
        ready = await _request(port, "/ready")
    finally:
        await server.close()

    assert live.startswith(b"HTTP/1.1 200 OK")
    assert live.endswith(b'{"status":"ok"}')
    assert ready.startswith(b"HTTP/1.1 200 OK")


async def test_health_server_rejects_unknown_path() -> None:
    server = RuntimeHealthServer(port=1, host="127.0.0.1")
    server._server = await asyncio.start_server(server._handle, server.host, 0)
    socket = server._server.sockets[0]
    port = int(socket.getsockname()[1])
    try:
        response = await _request(port, "/other")
    finally:
        await server.close()

    assert response.startswith(b"HTTP/1.1 404 Not Found")


async def test_health_server_keeps_live_open_when_readiness_is_blocked() -> None:
    server = RuntimeHealthServer(port=1, host="127.0.0.1", readiness=lambda: False)
    server._server = await asyncio.start_server(server._handle, server.host, 0)
    socket = server._server.sockets[0]
    port = int(socket.getsockname()[1])
    try:
        live = await _request(port, "/live")
        ready = await _request(port, "/ready")
    finally:
        await server.close()

    assert live.startswith(b"HTTP/1.1 200 OK")
    assert ready.startswith(b"HTTP/1.1 503 Service Unavailable")
    assert ready.endswith(b'{"status":"not-ready"}')
