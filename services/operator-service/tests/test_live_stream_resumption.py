"""Focused replay, cursor, and snapshot contracts for Live SSE."""

from __future__ import annotations

import asyncio

import pytest
from fdai_operator_service.composition import _live_activity_key
from fdai_operator_service.streaming.live_stream import (
    LiveStreamDelivery,
    LiveStreamEvent,
    LiveStreamHub,
    _encode_legacy_delivery,
    _live_chunks,
    make_live_stream_route,
)
from starlette.requests import Request


def _activity(instance: str, status: str = "completed") -> LiveStreamEvent:
    return LiveStreamEvent(
        event_id=f"{instance}:{status}",
        event_type="activity",
        payload={
            "type": "agent.operational-activity",
            "activity_id": f"{instance}:{status}",
            "activity_instance_id": instance,
            "status": status,
        },
    )


async def test_latest_activity_snapshot_and_recent_stage_are_separate() -> None:
    hub = LiveStreamHub(
        latest_key=_live_activity_key,
        replay_capacity=4,
        replay_window_seconds=60.0,
        stream_epoch="a" * 16,
    )
    activity = _activity("inventory.scan:attempt-1")
    stage = LiveStreamEvent(event_id="stage-1", payload={"stage": "route"})
    await hub.publish(activity)
    await hub.publish(stage)

    subscription = hub.subscribe_deliveries()
    snapshot = await anext(subscription)
    delta = await anext(subscription)

    assert snapshot.event == activity
    assert snapshot.snapshot is True
    assert snapshot.sequence is None
    assert delta.event == stage
    assert delta.sequence == 2
    await subscription.aclose()


async def test_snapshot_seed_is_unsequenced_and_atomic() -> None:
    hub = LiveStreamHub(latest_key=_live_activity_key)
    valid = _activity("inventory.scan:attempt-1")
    invalid = LiveStreamEvent(
        event_id="invalid",
        event_type="activity",
        payload={},
    )

    with pytest.raises(ValueError, match="snapshot key"):
        await hub.seed_latest((valid, invalid))
    empty = hub.subscribe_deliveries()
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(empty), timeout=0.01)

    await hub.seed_latest((valid,))
    snapshot = await anext(hub.subscribe_deliveries())
    assert snapshot.event == valid
    assert snapshot.sequence is None
    assert hub.next_sequence == 1


async def test_queue_loss_is_stamped_on_next_surviving_delta() -> None:
    hub = LiveStreamHub(maximum_queue_size=1)
    subscription = hub.subscribe_deliveries()
    waiting = asyncio.create_task(anext(subscription))
    await asyncio.sleep(0)
    first = LiveStreamEvent(event_id="event-1", payload={"sequence": 1})
    second = LiveStreamEvent(event_id="event-2", payload={"sequence": 2})
    third = LiveStreamEvent(event_id="event-3", payload={"sequence": 3})

    await hub.publish(first)
    assert (await waiting).event == first
    await hub.publish(second)
    await hub.publish(third)

    delivered = await anext(subscription)
    assert delivered.event == third
    assert delivered.dropped_before == 1
    await subscription.aclose()


async def test_fully_expired_resume_gap_is_stamped_on_next_delta() -> None:
    now = [0.0]
    hub = LiveStreamHub(
        replay_capacity=2,
        replay_window_seconds=1.0,
        clock=lambda: now[0],
        stream_epoch="b" * 16,
    )
    await hub.publish(LiveStreamEvent(event_id="event-1", payload={"sequence": 1}))
    await hub.publish(LiveStreamEvent(event_id="event-2", payload={"sequence": 2}))
    now[0] = 2.0
    subscription = hub.subscribe_deliveries(after_sequence=1)
    waiting = asyncio.create_task(anext(subscription))
    await asyncio.sleep(0)

    await hub.publish(LiveStreamEvent(event_id="event-3", payload={"sequence": 3}))
    delivery = await waiting

    assert delivery.sequence == 3
    assert delivery.dropped_before == 1
    await subscription.aclose()


@pytest.mark.parametrize("cursor", ["not an operator cursor", f"{'a' * 16}:1"])
async def test_route_rejects_malformed_or_ahead_cursor(cursor: str) -> None:
    hub = LiveStreamHub(stream_epoch="a" * 16)
    route = make_live_stream_route(hub=hub, authorize=lambda request: object())
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/live/stream",
            "raw_path": b"/live/stream",
            "query_string": b"",
            "headers": [(b"last-event-id", cursor.encode())],
            "client": ("127.0.0.1", 1),
            "server": ("127.0.0.1", 8010),
        }
    )

    response = await route.endpoint(request)

    assert response.status_code == 400


async def test_epoch_change_resets_to_unsequenced_snapshot() -> None:
    async def connected() -> bool:
        return False

    hub = LiveStreamHub(
        latest_key=_live_activity_key,
        stream_epoch="a" * 16,
    )
    await hub.seed_latest((_activity("inventory.scan:attempt-1"),))
    chunks = _live_chunks(
        hub=hub,
        is_disconnected=connected,
        keepalive_seconds=60.0,
        cursor_epoch="b" * 16,
        after_sequence=20,
    )

    hello = await anext(chunks)
    gap = await anext(chunks)
    snapshot = await anext(chunks)

    assert b'"cursor_reset":true' in hello
    assert b'"reason":"stream_epoch_changed"' in gap
    assert snapshot.startswith(b"event: activity-snapshot\n")
    assert not snapshot.startswith(b"id:")
    await chunks.aclose()


async def test_valid_cursor_replays_only_missing_deltas() -> None:
    async def connected() -> bool:
        return False

    hub = LiveStreamHub(
        replay_capacity=4,
        replay_window_seconds=60.0,
        stream_epoch="a" * 16,
    )
    for sequence in range(1, 4):
        await hub.publish(
            LiveStreamEvent(
                event_id=f"stage-{sequence}",
                payload={"sequence": sequence},
            )
        )
    chunks = _live_chunks(
        hub=hub,
        is_disconnected=connected,
        keepalive_seconds=60.0,
        cursor_epoch=hub.stream_epoch,
        after_sequence=1,
    )

    await anext(chunks)
    second = await anext(chunks)
    third = await anext(chunks)

    assert second.startswith(f"id: {hub.stream_epoch}:2\n".encode())
    assert third.startswith(f"id: {hub.stream_epoch}:3\n".encode())
    await chunks.aclose()


async def test_nonresumable_agent_stream_keeps_domain_event_id() -> None:
    async def connected() -> bool:
        return False

    hub = LiveStreamHub(latest_key=lambda event: "Huginn")
    await hub.publish(
        LiveStreamEvent(
            event_id="Huginn:2026-09-14T00:00:00+00:00",
            event_type="message",
            payload={"type": "agent.state"},
        )
    )
    chunks = _live_chunks(
        hub=hub,
        is_disconnected=connected,
        keepalive_seconds=60.0,
        channel="aw.pantheon.agents",
        resumable=False,
    )
    await anext(chunks)
    encoded = await anext(chunks)

    assert encoded.startswith(b"id: Huginn:2026-09-14T00:00:00+00:00\nevent: message\n")
    await chunks.aclose()


def test_nonresumable_agent_delivery_keeps_gap_advisory() -> None:
    encoded = _encode_legacy_delivery(
        LiveStreamDelivery(
            event=LiveStreamEvent(
                event_id="agent-event-1",
                event_type="message",
                payload={"type": "agent.state"},
            ),
            sequence=4,
            dropped_before=3,
        )
    )

    assert b"id: agent-event-1\n" in encoded
    assert b"dropped: 3\n" in encoded
