"""Round-3 SSE streaming hardening: serializer injection guards + route fail-close.

R1  id CR/LF stripped
R2  event CR/LF stripped + empty -> "message"
R3  data multi-line emitted as spec-correct data: fields (no frame split)
R4  data length capped
R5  retry_ms negative omitted
R6  _encode_sse_frame sanitized
R7  route event_pump fails closed (stream ends, never half-dead)
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fdai.delivery.operator_api.streaming.live_route import _offer_latest
from fdai.delivery.operator_api.streaming.live_stream import (
    _MAX_SSE_DATA_CHARS,
    _encode_sse_event,
    _encode_sse_frame,
    make_live_stream_route,
)
from fdai.shared.providers.sse import SseEvent


def _lines(evt: SseEvent) -> list[str]:
    return _encode_sse_event(evt).decode().split("\n")


# --- R1 / R2: id + event CR/LF injection ---------------------------------


def test_r1_id_crlf_is_flattened() -> None:
    wire = _encode_sse_event(SseEvent(id="a\nid: forged", event="e", data="{}")).decode()
    # The newline is flattened to a space: no second, forged `id:`/field line.
    assert "\nid: forged" not in wire
    assert wire.startswith("id: a id: forged")  # one line, injection neutralized


def test_r2_event_crlf_flattened_and_empty_defaults() -> None:
    wire = _encode_sse_event(SseEvent(id=None, event="x\ndata: forged", data="{}")).decode()
    assert "\ndata: forged" not in wire  # the forged data line is neutralized
    empty = _encode_sse_event(SseEvent(id=None, event="   ", data="{}")).decode()
    assert empty.startswith("event: message")


# --- R3: data multi-line is spec-correct, never a bare newline -----------


def test_r3_data_newline_becomes_multiple_data_lines() -> None:
    lines = _lines(SseEvent(id=None, event="e", data="line1\nline2"))
    assert "data: line1" in lines
    assert "data: line2" in lines


def test_r3_crlf_and_cr_normalized() -> None:
    lines = _lines(SseEvent(id=None, event="e", data="a\r\nb\rc"))
    assert lines.count("data: a") == 1
    assert "data: b" in lines
    assert "data: c" in lines


def test_r3_injection_cannot_forge_a_second_event() -> None:
    # A payload trying to inject a blank line (event boundary) + a forged
    # event must NOT split into two SSE frames.
    evt = SseEvent(id="x\n\nevent: forged\ndata: 1", event="e", data="{}")
    wire = _encode_sse_event(evt).decode()
    # Exactly one frame terminator (the trailing blank line).
    assert wire.count("\n\n") == 1
    assert wire.endswith("\n\n")


# --- R4: data length cap -------------------------------------------------


def test_r4_data_is_capped() -> None:
    huge = "x" * (_MAX_SSE_DATA_CHARS + 5000)
    lines = _lines(SseEvent(id=None, event="e", data=huge))
    data_payload = "".join(
        line.removeprefix("data: ") for line in lines if line.startswith("data: ")
    )
    assert len(data_payload) <= _MAX_SSE_DATA_CHARS


# --- R5: retry guard -----------------------------------------------------


def test_r5_negative_retry_omitted() -> None:
    neg = _encode_sse_event(SseEvent(id=None, event="e", data="{}", retry_ms=-1)).decode()
    assert "retry:" not in neg
    pos = _encode_sse_event(SseEvent(id=None, event="e", data="{}", retry_ms=2000)).decode()
    assert "retry: 2000" in pos


# --- R6: hello/control frame sanitized -----------------------------------


def test_r6_frame_data_multiline_and_valid() -> None:
    wire = _encode_sse_frame({"event": "hello", "note": "x"}, kind="hello").decode()
    assert wire.startswith("event: hello")
    assert wire.count("\n\n") == 1
    # data is valid single-line JSON.
    data_line = next(ln for ln in wire.split("\n") if ln.startswith("data: "))
    assert json.loads(data_line.removeprefix("data: "))["event"] == "hello"


# --- R7: route event_pump fails closed -----------------------------------


class _FailingSink:
    async def publish(self, channel: str, event: SseEvent) -> None:  # noqa: ARG002
        return None

    def subscribe(self, channel: str) -> AsyncIterator[SseEvent]:  # noqa: ARG002
        return self._gen()

    async def _gen(self) -> AsyncIterator[SseEvent]:
        raise RuntimeError("backend down")
        yield  # pragma: no cover - makes this an async generator


class _FakeRequest:
    async def is_disconnected(self) -> bool:
        return False


async def test_r7_stream_ends_when_sink_errors() -> None:
    async def _authorize(_request: object) -> str:
        return "tester"

    route = make_live_stream_route(
        sink=_FailingSink(),  # type: ignore[arg-type]
        channel="c",
        path="/s",
        keepalive_seconds=0.05,
        authorize=_authorize,
    )
    response = await route.endpoint(_FakeRequest())  # type: ignore[arg-type,attr-defined]

    frames: list[bytes] = []

    async def _drain() -> None:
        async for chunk in response.body_iterator:  # type: ignore[attr-defined]
            frames.append(chunk)

    # Must terminate on its own (never half-dead) - a generous bound guards
    # against a regression that would hang.
    await asyncio.wait_for(_drain(), timeout=3.0)

    assert frames  # the hello frame was sent
    assert any(b"hello" in f for f in frames)
    # The stream closed itself after the sink error (the drain completed).


def test_r8_overflow_keeps_newest_event() -> None:
    queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=2)
    queue.put_nowait(b"oldest")
    queue.put_nowait(b"middle")

    dropped = _offer_latest(queue, b"newest")

    assert dropped is True
    assert queue.get_nowait() == b"middle"
    assert queue.get_nowait() == b"newest"
