"""Bound actual native decoder output before inventory response retention."""

from __future__ import annotations

import asyncio
import gzip
import json
import zlib

import httpx
import pytest
from fdai.delivery import http_response
from fdai.delivery.azure.arg_transport import fetch_arg_row_pages
from fdai.delivery.azure.arm_inventory_transport import fetch_arm_json
from fdai.delivery.azure.arm_inventory_vm_state import ArmInventoryError
from fdai.delivery.azure.resource_health_inventory import (
    AzureResourceHealthInventoryConfig,
    AzureResourceHealthInventoryEnricher,
)
from fdai.delivery.azure.static_web_app_inventory import (
    AzureStaticWebAppInventoryConfig,
    AzureStaticWebAppInventoryEnricher,
)
from fdai.delivery.http_response import ResponseBodyTooLargeError, read_bounded_response
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity

_OWNERS = ("arg", "arm", "static_web_app", "resource_health")
_ENCODINGS = ("identity", "gzip", "deflate", "raw_deflate")
_PAYLOAD = {
    "name": "default",
    "data": [],
    "value": [],
    "properties": {
        "status": "Ready",
        "lastUpdatedOn": "2026-01-01T00:00:00Z",
        "availabilityState": "Available",
        "reportedTime": "2026-01-01T00:00:00Z",
    },
}


def _encode(content, encoding):
    if encoding == "gzip":
        return gzip.compress(content)
    if encoding == "deflate":
        return zlib.compress(content)
    if encoding == "raw_deflate":
        compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        return compressor.compress(content) + compressor.flush()
    return content


class _Body(httpx.AsyncByteStream):
    def __init__(self, content, *, chunk_size=65536):
        self.content = content
        self.chunk_size = chunk_size
        self.closed = False

    async def __aiter__(self):
        for offset in range(0, len(self.content), self.chunk_size):
            yield self.content[offset : offset + self.chunk_size]

    async def aclose(self):
        self.closed = True


def _response(content, encoding, *, chunk_size=65536, status=200):
    body = _Body(content, chunk_size=chunk_size)
    return (
        httpx.Response(
            status,
            headers={"content-encoding": encoding.removeprefix("raw_")},
            stream=body,
        ),
        body,
    )


def _track_decoder(monkeypatch):
    factory = zlib.decompressobj
    calls = []

    class Decoder:
        def __init__(self, *args, **kwargs):
            self.decoder = factory(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self.decoder, name)

        def decompress(self, content, max_length=0):
            assert max_length > 0, "native decoder output must never be unlimited"
            result = self.decoder.decompress(content, max_length)
            calls.append((max_length, len(result)))
            return result

        def flush(self, *args):
            pytest.fail("an unbounded native decoder flush is not admissible")

    monkeypatch.setattr(http_response.zlib, "decompressobj", Decoder)
    return calls


async def _call_owner(owner, client, *, limit=1024):
    identity = StaticWorkloadIdentity(
        audience="https://management.azure.com/.default",
        token="test-token",  # noqa: S106 - synthetic credential, no network transport
    )
    if owner == "arg":
        return await fetch_arg_row_pages(
            identity=identity,
            http_client=client,
            audience="https://management.azure.com/.default",
            endpoint="https://management.azure.com",
            api_version="2022-10-01",
            subscriptions=("sub-example",),
            query="Resources",
            result_name="example",
            page_size=1,
            max_pages=1,
            timeout_seconds=1,
            error_type=RuntimeError,
            max_response_bytes=limit,
            max_total_response_bytes=limit,
            max_attempts=1,
        )
    if owner == "arm":
        return await fetch_arm_json(
            client=client,
            url="https://management.azure.com/example",
            headers={},
            resource_type="example",
            timeout_seconds=1,
            max_response_bytes=limit,
            max_attempts=1,
        )
    resource = ResourceRecord(
        "example",
        "static-web-app",
        provider_ref=(
            "/subscriptions/sub-example/resourceGroups/example/"
            "providers/Microsoft.Web/staticSites/example"
        ),
    )
    if owner == "static_web_app":
        enricher = AzureStaticWebAppInventoryEnricher(
            identity=identity,
            http_client=client,
            config=AzureStaticWebAppInventoryConfig(
                subscription_ids=("sub-example",), max_response_bytes=limit
            ),
        )
    else:
        enricher = AzureResourceHealthInventoryEnricher(
            identity=identity,
            http_client=client,
            config=AzureResourceHealthInventoryConfig(
                subscription_ids=("sub-example",), max_response_bytes=limit
            ),
        )
    return await enricher._read(resource, token="test-token")  # noqa: S106


@pytest.mark.parametrize("encoding", _ENCODINGS)
@pytest.mark.parametrize("chunk_size", [1, 17, 65536])
async def test_complete_response_preserves_exact_limit_and_split_headers(encoding, chunk_size):
    content = b"x" * 1024
    response, body = _response(_encode(content, encoding), encoding, chunk_size=chunk_size)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
        async with client.stream("GET", "https://example.com") as streamed:
            assert await read_bounded_response(streamed, max_bytes=1024) == content
    assert body.closed


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "raw_deflate"])
@pytest.mark.parametrize("owner", _OWNERS)
async def test_every_owner_bounds_native_bomb_allocation(monkeypatch, owner, encoding):
    compressed = _encode(b"x" * (1024 * 1024), encoding)
    calls = _track_decoder(monkeypatch)
    response, body = _response(compressed, encoding)

    def handler(request):
        assert request.headers["accept-encoding"] == "gzip, deflate"
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        if owner in {"arg", "arm"}:
            with pytest.raises(RuntimeError, match="exceeded"):
                await _call_owner(owner, client)
        else:
            assert await _call_owner(owner, client) == "response_too_large"
    assert calls
    assert all(0 < allowance <= 1025 and output <= allowance for allowance, output in calls)
    assert sum(output for _, output in calls) == 1025
    assert body.closed


@pytest.mark.parametrize("encoding", _ENCODINGS)
@pytest.mark.parametrize("owner", _OWNERS)
async def test_every_owner_preserves_valid_response(owner, encoding):
    payload = json.dumps(_PAYLOAD).encode()
    response, body = _response(_encode(payload, encoding), encoding)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
        result = await _call_owner(owner, client)
    if owner == "arg":
        assert result == ()
    elif owner == "arm":
        assert result == (_PAYLOAD, len(payload))
    else:
        assert result.state == ("Ready" if owner == "static_web_app" else "Available")
    assert body.closed


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "raw_deflate"])
@pytest.mark.parametrize("defect", ["truncated", "malformed", "trailing"])
async def test_compressed_integrity_is_checked_without_flush(encoding, defect):
    encoded = _encode(b"complete", encoding)
    if defect == "truncated":
        encoded = encoded[:-1]
    elif defect == "malformed":
        encoded = b"not-compressed"
    else:
        encoded += b"junk"
    response, _ = _response(encoded, encoding)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
        async with client.stream("GET", "https://example.com") as streamed:
            with pytest.raises(httpx.DecodingError):
                await read_bounded_response(streamed, max_bytes=1024)


@pytest.mark.parametrize("owner", _OWNERS)
async def test_owner_reports_truncated_encoding_without_retry(owner):
    response, body = _response(gzip.compress(json.dumps(_PAYLOAD).encode())[:-1], "gzip")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
        if owner in {"arg", "arm"}:
            with pytest.raises(RuntimeError, match="invalid compressed"):
                await _call_owner(owner, client)
        else:
            assert await _call_owner(owner, client) == "response_invalid"
    assert body.closed


async def test_gzip_members_share_one_output_budget(monkeypatch):
    members = gzip.compress(b"x" * 512) + gzip.compress(b"y" * 513)
    calls = _track_decoder(monkeypatch)
    response, _ = _response(members, "gzip")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
        async with client.stream("GET", "https://example.com") as streamed:
            with pytest.raises(ResponseBodyTooLargeError):
                await read_bounded_response(streamed, max_bytes=1024)
    assert sum(output for _, output in calls) == 1025


async def test_gzip_members_complete_at_the_exact_limit():
    response, _ = _response(gzip.compress(b"first") + gzip.compress(b"second"), "gzip")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
        async with client.stream("GET", "https://example.com") as streamed:
            assert await read_bounded_response(streamed, max_bytes=11) == b"firstsecond"


@pytest.mark.parametrize("limit", [0, 1024, None])
async def test_empty_gzip_and_explicitly_disabled_ceiling(limit):
    content = b"" if limit == 0 else b"bounded"
    response, _ = _response(gzip.compress(content), "gzip")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
        async with client.stream("GET", "https://example.com") as streamed:
            assert await read_bounded_response(streamed, max_bytes=limit) == content


async def test_large_valid_output_keeps_native_calls_bounded(monkeypatch):
    content = b"x" * (1024 * 1024)
    encoded = gzip.compress(content)
    calls = _track_decoder(monkeypatch)
    response, _ = _response(encoded, "gzip")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
        async with client.stream("GET", "https://example.com") as streamed:
            assert await read_bounded_response(streamed, max_bytes=len(content)) == content
    assert max(allowance for allowance, _ in calls) == 65536
    assert sum(output for _, output in calls) == len(content)


@pytest.mark.parametrize("limit", [100, 156])
async def test_raw_deflate_preserves_a_zlib_shaped_prefix(monkeypatch, limit):
    encoded = b"\x78\x9c\x00\x63\xff" + b"x" * 156 + b"\x01\x00\x00\xff\xff"
    assert zlib.decompress(encoded, -zlib.MAX_WBITS) == b"x" * 156
    calls = _track_decoder(monkeypatch)
    response, _ = _response(encoded, "deflate")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
        async with client.stream("GET", "https://example.com") as streamed:
            if limit < 156:
                with pytest.raises(ResponseBodyTooLargeError):
                    await read_bounded_response(streamed, max_bytes=limit)
            else:
                assert await read_bounded_response(streamed, max_bytes=limit) == b"x" * 156
    assert calls
    assert all(0 < allowance <= limit + 1 and output <= allowance for allowance, output in calls)


async def test_wire_ceiling_also_bounds_empty_output_headers():
    encoded = gzip.compress(b"")
    encoded = encoded[:3] + b"\x08" + encoded[4:10] + b"x" * 67000 + b"\0" + encoded[10:]
    response, body = _response(encoded, "gzip")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
        async with client.stream("GET", "https://example.com") as streamed:
            with pytest.raises(ResponseBodyTooLargeError, match="wire"):
                await read_bounded_response(streamed, max_bytes=1024)
    assert body.closed


@pytest.mark.parametrize("encoding", ["br", "gzip, deflate", "unknown"])
async def test_unknown_or_stacked_encoding_is_explicit(encoding):
    response, _ = _response(b"{}", encoding)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
        async with client.stream("GET", "https://example.com") as streamed:
            with pytest.raises(httpx.DecodingError, match="unsupported"):
                await read_bounded_response(streamed, max_bytes=1024)


@pytest.mark.parametrize("owner", _OWNERS)
async def test_http_denial_is_not_decoded_as_inventory(owner):
    response, body = _response(b"invalid-compressed-body", "gzip", status=403)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
        if owner == "arg":
            with pytest.raises(RuntimeError, match="HTTP 403"):
                await _call_owner(owner, client)
        elif owner == "arm":
            with pytest.raises(ArmInventoryError, match="HTTP 403"):
                await _call_owner(owner, client)
        else:
            assert await _call_owner(owner, client) == "unauthorized"
    assert body.closed


@pytest.mark.parametrize("owner", _OWNERS)
@pytest.mark.parametrize("termination", ["cancellation", "deadline"])
async def test_cancellation_and_deadlines_close_each_owner_response(owner, termination):
    entered = asyncio.Event()

    class WaitingBody(_Body):
        async def __aiter__(self):
            entered.set()
            await asyncio.Event().wait()
            yield b""

    body = WaitingBody(b"")
    response = httpx.Response(200, headers={"content-encoding": "gzip"}, stream=body)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
        if termination == "deadline":
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(0):
                    await _call_owner(owner, client)
        else:
            task = asyncio.create_task(_call_owner(owner, client))
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    assert body.closed
