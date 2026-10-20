"""Bound verifier response allocation before decompression or body retention."""

from __future__ import annotations

import asyncio
import gzip
import json
import tracemalloc
import zlib
from collections.abc import AsyncIterator

import httpx
import pytest
from fdai.delivery.operational_evidence_transport import (
    BoundedOperationalEvidenceIssuer,
    HttpOperationalEvidenceTransport,
    read_verifier_readiness,
)
from fdai_service_contracts.operational_evidence import (
    OperationalEvidenceIssuanceRequest,
    OperationalEvidenceIssuanceResponse,
    OperationalEvidenceIssuanceStatus,
)

from tests.core.operational_evidence.support import MemoryProofStore
from tests.delivery.test_operational_evidence_transport import _attempt, _requester


class _Stream(httpx.AsyncByteStream):
    def __init__(self, body: bytes, *, stall: bool = False) -> None:
        self.body = body
        self.stall = stall
        self.chunks_read = 0
        self.closed = False
        self.started = asyncio.Event()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.started.set()
        if self.stall:
            await asyncio.Event().wait()
        for offset in range(0, len(self.body), 32 * 1024):
            self.chunks_read += 1
            yield self.body[offset : offset + 32 * 1024]

    async def aclose(self) -> None:
        self.closed = True


async def _observe(client: httpx.AsyncClient, kind: str, *, timeout: float = 2.0) -> None:
    if kind == "readiness":
        assert (
            await read_verifier_readiness(
                client, base_url="http://127.0.0.1:8791", timeout_seconds=timeout
            )
            is None
        )
    else:
        issuer = BoundedOperationalEvidenceIssuer(
            HttpOperationalEvidenceTransport(client, base_url="http://127.0.0.1:8791"),
            timeout_seconds=timeout,
        )
        result = await _attempt(_requester(issuer, MemoryProofStore()))
        assert result.status is OperationalEvidenceIssuanceStatus.UNAVAILABLE


@pytest.mark.parametrize("kind", ["issuance", "readiness"])
@pytest.mark.parametrize("encoding", ["identity", "gzip", "deflate", "raw-deflate"])
async def test_large_response_is_refused_without_unbounded_native_allocation(kind, encoding):
    body = b"x" * (2 * 1024 * 1024)
    if encoding == "gzip":
        body = gzip.compress(body)
    elif encoding == "deflate":
        body = zlib.compress(body)
    elif encoding == "raw-deflate":
        compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        body = compressor.compress(body) + compressor.flush()
    stream = _Stream(body)
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.method)
        return httpx.Response(
            200,
            headers={"content-encoding": "deflate" if encoding == "raw-deflate" else encoding},
            stream=stream,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tracemalloc.start()
        try:
            await _observe(client, kind)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
    assert requests == ["POST" if kind == "issuance" else "GET"]
    assert stream.closed
    assert peak < 512 * 1024
    if encoding == "identity":
        assert stream.chunks_read <= 2


@pytest.mark.parametrize("kind", ["issuance", "readiness"])
@pytest.mark.parametrize("status", [429, 503, 500])
async def test_failed_status_closes_without_reading_or_retrying_body(kind, status):
    stream = _Stream(b"do not read")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(status, stream=stream)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _observe(client, kind)
    assert len(calls) == 1
    assert stream.chunks_read == 0
    assert stream.closed


@pytest.mark.parametrize("kind", ["issuance", "readiness"])
async def test_body_deadline_closes_response_without_retry(kind):
    stream = _Stream(b"never returned", stall=True)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, stream=stream)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _observe(client, kind, timeout=0.01)
    assert len(calls) == 1
    assert stream.closed


@pytest.mark.parametrize("kind", ["issuance", "readiness"])
async def test_caller_cancellation_propagates_and_closes_response(kind):
    stream = _Stream(b"never returned", stall=True)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
    ) as client:
        task = asyncio.create_task(_observe(client, kind))
        await asyncio.wait_for(stream.started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert stream.closed


@pytest.mark.parametrize("kind", ["issuance", "readiness"])
@pytest.mark.parametrize("encoding", ["identity", "gzip", "deflate"])
@pytest.mark.parametrize("extra", [0, 1])
async def test_exact_decoded_response_ceiling_is_not_a_proxy_for_compressed_size(
    kind, encoding, extra
):
    streams = []
    sent_requests = []
    parsed_responses = []

    class TrackingTransport(HttpOperationalEvidenceTransport):
        async def send(
            self, request: OperationalEvidenceIssuanceRequest
        ) -> OperationalEvidenceIssuanceResponse:
            result = await super().send(request)
            parsed_responses.append(result)
            return result

    def handler(request: httpx.Request) -> httpx.Response:
        sent_requests.append(request)
        if kind == "issuance":
            sent = OperationalEvidenceIssuanceRequest.model_validate_json(request.content)
            body = OperationalEvidenceIssuanceResponse.unavailable(sent).model_dump_json().encode()
            limit = 4096
        else:
            body = json.dumps(
                {
                    "state": "unavailable",
                    "reasons": ["source_unavailable"],
                    "verifier_id": "operational-evidence-verifier",
                    "verifier_version": "1.0.0",
                    "trust_registry_pin": "sha256:" + "a" * 64,
                    "grant_registry_pin": "sha256:" + "b" * 64,
                }
            ).encode()
            limit = 8192
        body += b" " * (limit + extra - len(body))
        if encoding == "gzip":
            body = gzip.compress(body)
        elif encoding == "deflate":
            body = zlib.compress(body)
        stream = _Stream(body)
        streams.append(stream)
        return httpx.Response(200, headers={"content-encoding": encoding}, stream=stream)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        if kind == "issuance":
            result = await _attempt(
                _requester(
                    BoundedOperationalEvidenceIssuer(
                        TrackingTransport(client, base_url="http://127.0.0.1:8791")
                    ),
                    MemoryProofStore(),
                )
            )
            assert result.status is OperationalEvidenceIssuanceStatus.UNAVAILABLE
            assert len(parsed_responses) == (0 if extra else 1)
        else:
            readiness = await read_verifier_readiness(client, base_url="http://127.0.0.1:8791")
            assert (readiness is None) is bool(extra)
    assert len(sent_requests) == 1
    assert streams[0].closed
    assert sent_requests[0].headers["accept-encoding"] == "gzip, deflate"


async def test_connected_handoff_reuses_the_same_bounded_readiness_reader(monkeypatch):
    from fdai.delivery import operational_evidence_handoff_cli as handoff

    stream = _Stream(gzip.compress(b"x" * (2 * 1024 * 1024)))
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-encoding": "gzip"}, stream=stream)

    def client(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(handoff.httpx, "AsyncClient", client)
    tracemalloc.start()
    try:
        with pytest.raises(ValueError, match="readiness is unavailable"):
            await handoff._readiness("http://127.0.0.1:8791")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert stream.closed
    assert peak < 512 * 1024
