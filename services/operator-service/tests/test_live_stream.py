"""Focused contracts for the service-owned Live SSE fan-out surface."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fdai_operator_service.adapters.live_stage_kafka import (
    LiveStageKafkaConfig,
    LiveStageKafkaRelay,
)
from fdai_operator_service.streaming.live_stream import (
    LiveStreamEvent,
    LiveStreamHub,
    _encode_event,
    _live_chunks,
)
from fdai_operator_service.streaming.stage_frames import parse_stage_frame


async def test_live_stream_hub_isolates_bounded_subscribers() -> None:
    hub = LiveStreamHub(maximum_queue_size=2)
    subscription = hub.subscribe()
    waiting = asyncio.create_task(anext(subscription))
    await asyncio.sleep(0)

    first = LiveStreamEvent(event_id="event-1", payload={"sequence": 1})
    second = LiveStreamEvent(event_id="event-2", payload={"sequence": 2})
    third = LiveStreamEvent(event_id="event-3", payload={"sequence": 3})
    await hub.publish(first)
    assert await waiting == first

    await hub.publish(second)
    await hub.publish(third)
    await hub.publish(first)

    assert await anext(subscription) == third
    assert await anext(subscription) == first
    await subscription.aclose()


def test_live_stream_event_encoding_blocks_field_and_data_injection() -> None:
    encoded = _encode_event(
        LiveStreamEvent(
            event_id="event-1\nevent: forged",
            payload={"detail": "line-1\nline-2"},
        )
    ).decode()

    assert encoded.startswith("id: event-1 event: forged\nevent: stage\n")
    assert 'data: {"detail":"line-1\\nline-2"}\n\n' in encoded
    assert "\nevent: forged\n" not in encoded


def test_parse_stage_frame_accepts_only_current_valid_runtime_records() -> None:
    payload = {
        "event_id": "event-1",
        "correlation_id": "correlation-1",
        "stage": "route",
        "phase": "done",
        "source": "runtime-observed",
        "ts": datetime.now(UTC).isoformat(),
        "detail": {"tier": "t0"},
    }

    parsed = parse_stage_frame(payload)

    assert parsed is not None
    assert parsed.event_id == "event-1"
    assert parsed.payload == payload


def test_parse_stage_frame_rejects_unknown_future_and_inconsistent_records() -> None:
    valid = {
        "event_id": "event-1",
        "correlation_id": "correlation-1",
        "stage": "route",
        "phase": "done",
        "source": "runtime-observed",
        "ts": datetime.now(UTC).isoformat(),
    }

    assert parse_stage_frame({**valid, "stage": "invented"}) is None
    assert parse_stage_frame({**valid, "phase": "failed"}) is None
    assert parse_stage_frame({**valid, "error": "not failed"}) is None
    assert (
        parse_stage_frame({**valid, "ts": (datetime.now(UTC) + timedelta(hours=1)).isoformat()})
        is None
    )


async def test_live_stage_kafka_relay_publishes_then_commits() -> None:
    class FakeConsumer:
        def __init__(self) -> None:
            self.messages: asyncio.Queue[object] = asyncio.Queue()
            self.started = False
            self.stopped = False
            self.commits = 0

        async def start(self) -> None:
            self.started = True

        async def stop(self) -> None:
            self.stopped = True

        async def getone(self) -> object:
            return await self.messages.get()

        async def commit(self) -> None:
            self.commits += 1

    consumer = FakeConsumer()
    hub = LiveStreamHub()
    subscription = hub.subscribe()
    waiting = asyncio.create_task(anext(subscription))
    await asyncio.sleep(0)
    relay = LiveStageKafkaRelay(
        config=LiveStageKafkaConfig(
            bootstrap_servers="127.0.0.1:19092",
            security_protocol="PLAINTEXT",
        ),
        hub=hub,
        credential=None,
        consumer_factory=lambda: consumer,  # type: ignore[arg-type]
    )
    payload = {
        "event_id": "event-1",
        "correlation_id": "correlation-1",
        "stage": "route",
        "phase": "done",
        "source": "runtime-observed",
        "ts": datetime.now(UTC).isoformat(),
    }

    await relay.start()
    await consumer.messages.put(SimpleNamespace(value=json.dumps(payload).encode("utf-8")))

    assert await asyncio.wait_for(waiting, timeout=0.5) == LiveStreamEvent(
        event_id="event-1", payload=payload
    )
    assert consumer.commits == 1
    assert relay.readiness()
    await subscription.aclose()
    await relay.aclose()
    assert consumer.stopped


async def test_live_stream_keepalive_does_not_close_subscription() -> None:
    async def connected() -> bool:
        return False

    chunks = _live_chunks(
        hub=LiveStreamHub(),
        is_disconnected=connected,
        keepalive_seconds=0.001,
    )

    assert (await anext(chunks)).startswith(b"event: hello\n")
    assert await asyncio.wait_for(anext(chunks), timeout=0.1) == b": keepalive\n\n"
    assert await asyncio.wait_for(anext(chunks), timeout=0.1) == b": keepalive\n\n"
    await chunks.aclose()
