"""Round-3 SSE streaming hardening: broadcaster resilience + bounded sink.

R8  broadcaster relay retries after a transient bus error (channel recovers)
R9  InMemorySseSink optional bounded (drop-oldest) queue
R10 broadcaster sanitizes a payload-derived SSE id at the trust boundary
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from fdai.shared.providers.event_bus import EventEnvelope
from fdai.shared.providers.sse import SseEvent
from fdai.shared.providers.testing import InMemorySseSink
from fdai.shared.providers.testing.sse import _offer
from fdai.shared.streaming.broadcaster import (
    SseBroadcaster,
    _extract_correlation_id,
    _sanitize_id,
)

# --- R8: broadcaster retries a transient bus error -----------------------


class _FlakyBus:
    """First subscribe raises (transient); the second yields one envelope."""

    def __init__(self) -> None:
        self.subscribe_calls = 0

    def subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:  # noqa: ARG002
        self.subscribe_calls += 1
        if self.subscribe_calls == 1:
            return self._raising()
        return self._one()

    async def _raising(self) -> AsyncIterator[EventEnvelope]:
        raise RuntimeError("transient bus error")
        yield  # pragma: no cover - makes this an async generator

    async def _one(self) -> AsyncIterator[EventEnvelope]:
        yield EventEnvelope(topic="t", key="k", payload={"correlation_id": "c1"}, offset=0)


async def test_r8_relay_retries_after_transient_error() -> None:
    flaky = _FlakyBus()
    sink = InMemorySseSink()
    broadcaster = SseBroadcaster(
        event_bus=flaky,  # type: ignore[arg-type]
        sse_sink=sink,
        topic_channel_map={"t": "c"},
        retry_backoff_seconds=0.0,  # no delay in test
    )

    published: list[SseEvent] = []

    async def _capture(channel: str, event: SseEvent) -> None:  # noqa: ARG001
        published.append(event)

    sink.publish = _capture  # type: ignore[method-assign]

    # Drive one relay directly: subscribe#1 raises -> retry -> subscribe#2
    # yields one envelope -> published -> generator ends -> returns.
    await asyncio.wait_for(broadcaster._relay_topic("t", "c", "g"), timeout=2.0)

    assert flaky.subscribe_calls == 2  # retried past the transient failure
    assert published and published[0].id == "c1"


# --- R9: InMemorySseSink bounded (drop-oldest) ---------------------------


def _evt(n: int) -> SseEvent:
    return SseEvent(id=str(n), event="e", data="{}")


def test_r9_offer_drops_oldest_on_full_bounded_queue() -> None:
    queue: asyncio.Queue[SseEvent] = asyncio.Queue(maxsize=2)
    _offer(queue, _evt(1))
    _offer(queue, _evt(2))
    _offer(queue, _evt(3))  # full -> drop oldest (1)
    assert queue.get_nowait().id == "2"
    assert queue.get_nowait().id == "3"
    assert queue.empty()


def test_r9_offer_unbounded_keeps_all() -> None:
    queue: asyncio.Queue[SseEvent] = asyncio.Queue()  # maxsize 0 = unbounded
    for n in range(5):
        _offer(queue, _evt(n))
    assert queue.qsize() == 5


def test_r9_rejects_bad_max_queue() -> None:
    with pytest.raises(ValueError, match="max_queue"):
        InMemorySseSink(max_queue=0)


async def test_r9_unbounded_default_delivers_all() -> None:
    sink = InMemorySseSink()  # default None -> unbounded (historical behavior)
    received: list[SseEvent] = []
    ready = asyncio.Event()

    async def _consume() -> None:
        agen = sink.subscribe("c")
        ready.set()
        async for event in agen:
            received.append(event)
            if len(received) == 3:
                break

    task = asyncio.create_task(_consume())
    await ready.wait()
    await asyncio.sleep(0)
    for n in range(3):
        await sink.publish("c", _evt(n))
    await asyncio.wait_for(task, timeout=1.5)
    assert [e.id for e in received] == ["0", "1", "2"]


# --- R10: broadcaster sanitizes payload-derived SSE id -------------------


def test_r10_sanitize_id_strips_crlf() -> None:
    assert _sanitize_id("a\r\nid: forged") == "a id: forged"
    assert _sanitize_id("   ") is None
    assert _sanitize_id("x" * 5000) is not None
    assert len(_sanitize_id("x" * 5000) or "") <= 512


def test_r10_extract_correlation_id_is_sanitized() -> None:
    got = _extract_correlation_id({"correlation_id": "corr\n1"})
    assert got == "corr 1"
    assert "\n" not in (got or "")
    assert _extract_correlation_id({"correlation_id": ""}) is None
    assert _extract_correlation_id({}) is None
