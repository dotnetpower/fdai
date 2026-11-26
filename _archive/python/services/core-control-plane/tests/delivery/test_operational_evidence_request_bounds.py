"""Native verifier ingress is bounded before an issuance reference is parsed."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import httpx
import pytest
from aiohttp import web
from fdai.core.operational_evidence.issuance import (
    OperationalEvidenceVerifierEngine,
    VerifierIdentity,
)
from fdai.delivery import operational_evidence_server as server
from fdai.delivery.operational_evidence_transport import ISSUANCE_PATH
from fdai_service_contracts.operational_evidence import (
    OperationalEvidenceIssuanceRequest,
    OperationalEvidenceLocator,
    OperationalEvidenceLookup,
)

from tests.core.operational_evidence.support import NOW, POLICY, MemoryProofStore, anchors, history


def _body() -> bytes:
    return (
        OperationalEvidenceIssuanceRequest(
            attempt_id="a" * 32,
            lookup=OperationalEvidenceLookup(
                evidence_digest="sha256:" + "1" * 64,
                scope_digest="sha256:" + "2" * 64,
                purpose_id="operator-test-context-command",
                source_revision=POLICY,
            ),
            locator=OperationalEvidenceLocator(
                purpose_id="operator-test-context-command",
                coordinates={"idempotency_key": "source-command"},
            ),
            producer_id="core-control-plane",
            producer_version="1.0.0",
            requested_at=NOW,
        )
        .model_dump_json()
        .encode()
    )


@asynccontextmanager
async def _server(
    prepared_statuses: list[int] | None = None,
) -> AsyncIterator[tuple[str, int, MemoryProofStore]]:
    store = MemoryProofStore()
    registry = history()
    engine = OperationalEvidenceVerifierEngine(
        identity=VerifierIdentity("operational-evidence-verifier", "1.0.0"),
        history=lambda: registry,
        anchors=anchors(),
        readbacks=(),
        writer=store,
        clock=lambda: NOW,
    )
    app = server.build_verifier_app(
        engine,
        caller=server.LoopbackCallerAuthenticator("fdai_core"),
        readiness=lambda: server.VerifierReadiness(),
    )
    if prepared_statuses is not None:

        async def record_response(_: web.Request, response: web.StreamResponse) -> None:
            prepared_statuses.append(response.status)

        app.on_response_prepare.append(record_response)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = runner.addresses[0][:2]
    try:
        yield host, port, store
    finally:
        await runner.cleanup()


@pytest.mark.parametrize("deadline", [None, 0.05])
async def test_partial_issuance_body_has_a_server_deadline(
    monkeypatch: pytest.MonkeyPatch,
    deadline: float | None,
) -> None:
    if deadline is None:
        assert server._MAX_BODY_READ_SECONDS == 2.0
    else:
        monkeypatch.setattr(server, "_MAX_BODY_READ_SECONDS", deadline, raising=False)
    async with _server() as (host, port, store):
        reader, writer = await asyncio.open_connection(host, port)
        try:
            writer.write(
                f"POST {ISSUANCE_PATH} HTTP/1.1\r\nHost: localhost\r\n"
                "Content-Length: 100\r\nContent-Type: application/json\r\n"
                "Connection: close\r\n\r\n{".encode()
            )
            await writer.drain()
            status = await asyncio.wait_for(
                reader.readline(),
                timeout=3.0 if deadline is None else 0.5,
            )
            assert b" 408 " in status
            response = await asyncio.wait_for(reader.read(), timeout=0.5)
            assert b"connection: close" in response.lower()
            assert b"request_timeout" in response
            assert store.admissions == [] and store.rejections == []
        finally:
            writer.close()
            await writer.wait_closed()


@pytest.mark.parametrize("response_delay", [0.0, 0.15])
async def test_trickling_bytes_do_not_extend_the_total_body_deadline(
    monkeypatch: pytest.MonkeyPatch,
    response_delay: float,
) -> None:
    monkeypatch.setattr(server, "_MAX_BODY_READ_SECONDS", 0.06)
    prepared_statuses: list[int] = []
    async with _server(prepared_statuses) as (host, port, store):
        reader, writer = await asyncio.open_connection(host, port)
        writer.write(
            f"POST {ISSUANCE_PATH} HTTP/1.1\r\nHost: localhost\r\n"
            "Content-Length: 100\r\nConnection: close\r\n\r\n{".encode()
        )
        await writer.drain()

        async def trickle() -> None:
            try:
                for _ in range(99):
                    await asyncio.sleep(0.01)
                    writer.write(b" ")
                    await writer.drain()
            except (ConnectionResetError, BrokenPipeError):
                return

        sender = asyncio.create_task(trickle())
        try:
            await asyncio.sleep(response_delay)
            try:
                response = await asyncio.wait_for(reader.read(), timeout=0.5)
            except (ConnectionResetError, BrokenPipeError):
                assert prepared_statuses == [408]
            else:
                assert b" 408 " in response and b"request_timeout" in response
            assert prepared_statuses == [408]
            assert store.admissions == [] and store.rejections == []
        finally:
            sender.cancel()
            with suppress(asyncio.CancelledError):
                await sender
            writer.close()
            with suppress(ConnectionResetError, BrokenPipeError):
                await writer.wait_closed()


@pytest.mark.parametrize("size", [None, 16_383, 16_384, 16_385])
async def test_complete_request_preserves_exact_byte_limit(size: int | None) -> None:
    assert server._MAX_REQUEST_BYTES == 16_384
    body = _body()
    if size is not None:
        body += b" " * (size - len(body))
    async with _server() as (host, port, store), httpx.AsyncClient() as client:
        url = f"http://{host}:{port}{ISSUANCE_PATH}"
        response = await client.post(url, content=body)
        if size == 16_385:
            assert response.status_code == 413
            assert response.json() == {"error": "request_bound_exceeded"}
        else:
            assert response.status_code == 200
            assert response.json()["status"] == "unavailable"
        following = await client.post(url, content=_body())
        assert following.status_code == 200
        assert following.json()["status"] == "unavailable"
        if size != 16_385:
            assert following.extensions["network_stream"] is response.extensions["network_stream"]
        assert store.admissions == [] and store.rejections == []


async def test_complete_malformed_body_remains_explicit_and_redacted() -> None:
    async with _server() as (host, port, store), httpx.AsyncClient() as client:
        response = await client.post(
            f"http://{host}:{port}{ISSUANCE_PATH}", content=b"{private-body-marker"
        )
        assert response.status_code == 422
        assert response.json() == {"error": "request_invalid"}
        assert "private-body-marker" not in response.text
        assert store.admissions == [] and store.rejections == []


async def test_oversized_declared_body_is_refused_without_waiting_for_upload() -> None:
    async with _server() as (host, port, store):
        reader, writer = await asyncio.open_connection(host, port)
        try:
            writer.write(
                f"POST {ISSUANCE_PATH} HTTP/1.1\r\nHost: localhost\r\n"
                "Content-Length: 16385\r\nConnection: close\r\n\r\n{".encode()
            )
            await writer.drain()
            response = await asyncio.wait_for(reader.read(), timeout=0.5)
            assert b" 413 " in response
            assert b"request_bound_exceeded" in response
            assert store.admissions == [] and store.rejections == []
        finally:
            writer.close()
            await writer.wait_closed()
