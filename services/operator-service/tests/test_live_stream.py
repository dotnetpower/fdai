"""Focused contracts for the service-owned Live SSE fan-out surface."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fdai_operator_service.adapters.live_stage_kafka import (
    LiveStageKafkaConfig,
    LiveStageKafkaRelay,
)
from fdai_operator_service.composition import _agent_state_key
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


async def test_live_stream_hub_replays_latest_event_by_key_to_late_subscriber() -> None:
    hub = LiveStreamHub(latest_key=lambda event: str(event.payload["agent"]))
    stale = LiveStreamEvent(event_id="event-1", payload={"agent": "Huginn", "state": "idle"})
    latest = LiveStreamEvent(event_id="event-2", payload={"agent": "Huginn", "state": "watching"})
    other = LiveStreamEvent(event_id="event-3", payload={"agent": "Muninn", "state": "idle"})

    await hub.publish(stale)
    await hub.publish(latest)
    await hub.publish(other)
    subscription = hub.subscribe()

    assert await anext(subscription) == latest
    assert await anext(subscription) == other
    await subscription.aclose()


async def test_live_stream_hub_does_not_replay_without_latest_key() -> None:
    hub = LiveStreamHub()
    await hub.publish(LiveStreamEvent(event_id="event-1", payload={"sequence": 1}))
    subscription = hub.subscribe()

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(subscription), timeout=0.01)


async def test_agent_stream_hub_only_replays_agent_state() -> None:
    hub = LiveStreamHub(latest_key=_agent_state_key)
    activity = LiveStreamEvent(
        event_id="event-1",
        payload={"type": "incident.ticket", "agent": "Huginn"},
    )
    state = LiveStreamEvent(
        event_id="event-2",
        payload={"type": "agent.state", "agent": "Huginn", "state": "watching"},
    )

    await hub.publish(activity)
    await hub.publish(state)
    subscription = hub.subscribe()

    assert await anext(subscription) == state
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(subscription), timeout=0.01)


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
    agent_hub = LiveStreamHub()
    subscription = hub.subscribe()
    agent_subscription = agent_hub.subscribe()
    waiting = asyncio.create_task(anext(subscription))
    waiting_for_agent = asyncio.create_task(anext(agent_subscription))
    await asyncio.sleep(0)
    relay = LiveStageKafkaRelay(
        config=LiveStageKafkaConfig(
            bootstrap_servers="127.0.0.1:19092",
            security_protocol="PLAINTEXT",
        ),
        hub=hub,
        agent_hub=agent_hub,
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
    agent_event = await asyncio.wait_for(waiting_for_agent, timeout=0.5)
    assert agent_event.payload["type"] == "agent.state"
    assert agent_event.payload["agent"] == "Heimdall"
    waiting_for_runtime = asyncio.create_task(anext(agent_subscription))
    await asyncio.sleep(0)
    await consumer.messages.put(
        SimpleNamespace(
            value=json.dumps(
                {
                    "type": "agent.runtime-state",
                    "agent": "Huginn",
                    "state": "watching",
                    "ts": datetime.now(UTC).isoformat(),
                    "correlation_id": None,
                    "detail": "Runtime agent initialized",
                    "source": "runtime-observed",
                }
            ).encode("utf-8")
        )
    )
    runtime_event = await asyncio.wait_for(waiting_for_runtime, timeout=0.5)
    assert runtime_event.payload["type"] == "agent.state"
    assert runtime_event.payload["agent"] == "Huginn"
    assert consumer.commits == 2
    assert relay.readiness()
    await subscription.aclose()
    await agent_subscription.aclose()
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
