"""Read inventory response bodies without unbounded native decompression."""

from __future__ import annotations

import asyncio
import zlib

import httpx

BOUNDED_ACCEPT_ENCODING = "gzip, deflate"
_CHUNK_BYTES = 64 * 1024


class ResponseBodyTooLargeError(ValueError):
    """The response exceeded its decoded or wire-byte allowance."""


async def read_bounded_response(response: httpx.Response, *, max_bytes: int | None) -> bytes:
    """Bound native output before retention, with one byte of excess detection.

    The caller owns response closure, status handling, and deadlines. A preloaded
    response is checked without decoding it again; production callers stream raw
    responses. ``None`` retains ARG's explicit opt-out from a byte ceiling.
    """
    if max_bytes is not None and (type(max_bytes) is not int or max_bytes < 0):
        raise ValueError("response byte limit MUST be non-negative")
    if response.is_stream_consumed:
        if max_bytes is not None and len(response.content) > max_bytes:
            raise ResponseBodyTooLargeError("response body exceeds its byte limit")
        return response.content
    encoding = response.headers.get("content-encoding", "identity").strip().lower()
    if encoding not in {"identity", "gzip", "deflate"}:
        raise httpx.DecodingError("unsupported inventory response content encoding")
    decoder = zlib.decompressobj(zlib.MAX_WBITS | 16) if encoding == "gzip" else None
    raw_deflate_fallback = False
    prefix = b""
    content = bytearray()
    wire_bytes = 0
    async for raw in response.aiter_raw(chunk_size=_CHUNK_BYTES):
        wire_bytes += len(raw)
        if max_bytes is not None and wire_bytes > max_bytes + _CHUNK_BYTES:
            raise ResponseBodyTooLargeError("response wire body exceeds its byte limit")
        if encoding == "identity":
            if max_bytes is not None and len(content) + len(raw) > max_bytes:
                raise ResponseBodyTooLargeError("response body exceeds its byte limit")
            content.extend(raw)
            continue
        if decoder is None:
            prefix += raw
            if len(prefix) < 2:
                continue
            zlib_header = prefix[0] & 15 == 8 and int.from_bytes(prefix[:2]) % 31 == 0
            decoder = zlib.decompressobj(zlib.MAX_WBITS if zlib_header else -zlib.MAX_WBITS)
            raw_deflate_fallback = zlib_header
            raw, prefix = prefix, b""
        while raw:
            if decoder.eof:
                if encoding != "gzip":
                    raise httpx.DecodingError("trailing data in inventory deflate response")
                decoder = zlib.decompressobj(zlib.MAX_WBITS | 16)
            allowance = (
                _CHUNK_BYTES
                if max_bytes is None
                else min(_CHUNK_BYTES, max_bytes - len(content) + 1)
            )
            try:
                decoded = decoder.decompress(raw, allowance)
            except zlib.error as exc:
                if not raw_deflate_fallback:
                    raise httpx.DecodingError("invalid compressed inventory response") from exc
                decoder = zlib.decompressobj(-zlib.MAX_WBITS)
                try:
                    decoded = decoder.decompress(raw, allowance)
                except zlib.error as raw_error:
                    raise httpx.DecodingError(
                        "invalid compressed inventory response"
                    ) from raw_error
            raw_deflate_fallback = False
            if max_bytes is not None and len(content) + len(decoded) > max_bytes:
                raise ResponseBodyTooLargeError("response body exceeds its byte limit")
            content.extend(decoded)
            raw = decoder.unused_data if decoder.eof else decoder.unconsumed_tail
            await asyncio.sleep(0)
    if encoding != "identity" and (decoder is None or not decoder.eof):
        raise httpx.DecodingError("truncated compressed inventory response")
    return bytes(content)
