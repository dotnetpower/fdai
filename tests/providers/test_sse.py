"""SSE sink contract + broadcaster tests."""

from __future__ import annotations

import asyncio
import json

import pytest

from fdai.shared.providers import EventBus, SseEvent, SseSink
from fdai.shared.providers.testing import InMemoryEventBus, InMemorySseSink
from fdai.shared.streaming import SseBroadcaster

# ---------------------------------------------------------------------------
# Structural
# ---------------------------------------------------------------------------


def test_in_memory_sse_sink_satisfies_protocol() -> None:
    sink: SseSink = InMemorySseSink()
    assert isinstance(sink, SseSink)


# ---------------------------------------------------------------------------
# InMemorySseSink behaviour
# ---------------------------------------------------------------------------


async def test_publish_before_subscribe_is_not_replayed() -> None:
    """Standard SSE / pub-sub semantics: late joiners start fresh."""
    sink = InMemorySseSink()
    await sink.publish(
        "aw.audit.stream",
        SseEvent(id="evt-1", event="audit.entry.appended", data="{}"),
    )

    got: list[SseEvent] = []

    async def _consume() -> None:
        async for event in sink.subscribe("aw.audit.stream"):
            got.append(event)

    task = asyncio.create_task(_consume())
    # Give the subscribe loop a chance to register.
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert got == []


async def test_publish_after_subscribe_reaches_the_subscriber() -> None:
    sink = InMemorySseSink()
    received: list[SseEvent] = []
    ready = asyncio.Event()

    async def _consume() -> None:
        agen = sink.subscribe("aw.audit.stream")
        ready.set()
        async for event in agen:
            received.append(event)
            if len(received) == 2:
                break

    task = asyncio.create_task(_consume())
    await ready.wait()
    # Yield to the consumer so its queue is registered before publish().
    await asyncio.sleep(0)

    await sink.publish("aw.audit.stream", SseEvent(id="1", event="tick", data="{}"))
    await sink.publish("aw.audit.stream", SseEvent(id="2", event="tick", data="{}"))

    await asyncio.wait_for(task, timeout=1.0)
    assert [e.id for e in received] == ["1", "2"]


async def test_multiple_subscribers_all_receive_broadcast() -> None:
    sink = InMemorySseSink()
    a: list[str | None] = []
    b: list[str | None] = []
    ready_a = asyncio.Event()
    ready_b = asyncio.Event()

    async def _consume_a() -> None:
        agen = sink.subscribe("aw.audit.stream")
        ready_a.set()
        async for e in agen:
            a.append(e.id)
            if len(a) == 3:
                break

    async def _consume_b() -> None:
        agen = sink.subscribe("aw.audit.stream")
        ready_b.set()
        async for e in agen:
            b.append(e.id)
            if len(b) == 3:
                break

    task_a = asyncio.create_task(_consume_a())
    task_b = asyncio.create_task(_consume_b())
    await ready_a.wait()
    await ready_b.wait()
    await asyncio.sleep(0)  # let the subscribe async-gens register their queues

    for i in range(3):
        await sink.publish("aw.audit.stream", SseEvent(id=str(i), event="tick", data="{}"))

    await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=1.0)
    assert a == ["0", "1", "2"]
    assert b == ["0", "1", "2"]


async def test_subscriber_detaches_on_cancel() -> None:
    sink = InMemorySseSink()
    ready = asyncio.Event()

    async def _consume() -> None:
        agen = sink.subscribe("aw.audit.stream")
        ready.set()
        async for _ in agen:
            pass

    task = asyncio.create_task(_consume())
    await ready.wait()
    await asyncio.sleep(0)
    assert sink.subscriber_count("aw.audit.stream") == 1

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # The `finally` block in the async generator should have run.
    assert sink.subscriber_count("aw.audit.stream") == 0


# ---------------------------------------------------------------------------
# SseBroadcaster
# ---------------------------------------------------------------------------


async def test_broadcaster_relays_event_bus_to_sse_channel() -> None:
    bus: EventBus = InMemoryEventBus()
    sink = InMemorySseSink()
    broadcaster = SseBroadcaster(
        event_bus=bus,
        sse_sink=sink,
        topic_channel_map={"aw.change.events": "aw.change.stream"},
    )

    received: list[SseEvent] = []
    ready = asyncio.Event()

    async def _consume() -> None:
        agen = sink.subscribe("aw.change.stream")
        ready.set()
        async for event in agen:
            received.append(event)
            if len(received) == 2:
                break

    consume_task = asyncio.create_task(_consume())
    await ready.wait()
    await asyncio.sleep(0)

    await broadcaster.run()

    await bus.publish(
        "aw.change.events",
        key="rg-example",
        payload={"correlation_id": "corr-a", "event_id": "evt-1", "n": 1},
    )
    await bus.publish(
        "aw.change.events",
        key="rg-example",
        payload={"event_id": "evt-2", "n": 2},
    )

    try:
        await asyncio.wait_for(consume_task, timeout=1.5)
    finally:
        await broadcaster.stop()

    assert len(received) == 2
    # Correlation id is used as the SSE `id:` field when present.
    assert received[0].id == "corr-a"
    # Fallback to event_id when correlation is absent.
    assert received[1].id == "evt-2"
    # Data is JSON-encoded and MUST embed the original topic + payload.
    body = json.loads(received[0].data)
    assert body["topic"] == "aw.change.events"
    assert body["payload"]["n"] == 1


async def test_broadcaster_stop_is_idempotent() -> None:
    bus: EventBus = InMemoryEventBus()
    sink = InMemorySseSink()
    broadcaster = SseBroadcaster(
        event_bus=bus,
        sse_sink=sink,
        topic_channel_map={"t": "c"},
    )
    await broadcaster.run()
    await broadcaster.stop()
    await broadcaster.stop()  # second call must not raise


async def test_broadcaster_run_after_start_and_stop_raises() -> None:
    """Regression: run() -> stop() -> run() MUST raise, not silently no-op.

    A prior ordering checked `_started` before `_stopped`, so after the
    start-stop cycle a second run() short-circuited on `_started=True`
    and returned silently, making the RuntimeError guard unreachable.
    """
    bus: EventBus = InMemoryEventBus()
    sink = InMemorySseSink()
    broadcaster = SseBroadcaster(
        event_bus=bus,
        sse_sink=sink,
        topic_channel_map={"t": "c"},
    )
    await broadcaster.run()
    await broadcaster.stop()
    with pytest.raises(RuntimeError, match="already stopped"):
        await broadcaster.run()


async def test_broadcaster_empty_topic_map_is_rejected() -> None:
    bus: EventBus = InMemoryEventBus()
    sink = InMemorySseSink()
    with pytest.raises(ValueError):
        SseBroadcaster(event_bus=bus, sse_sink=sink, topic_channel_map={})
