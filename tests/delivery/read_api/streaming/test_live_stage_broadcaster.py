"""Tests for the production Kafka-to-Live stage broadcaster."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from fdai.delivery.read_api.streaming.live_stage_broadcaster import LiveStageBroadcaster
from fdai.shared.providers.stage_publisher import StageEvent, StageName, StagePhase
from fdai.shared.providers.testing import InMemorySseSink
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.streaming.stage_publisher import SseSinkStagePublisher


async def _drain(broadcaster: LiveStageBroadcaster) -> None:
    await broadcaster.run()
    task = broadcaster._task
    assert task is not None
    await asyncio.wait_for(task, timeout=5.0)
    await broadcaster.stop()


def _frame() -> dict[str, object]:
    return StageEvent(
        event_id="evt-live-prod",
        correlation_id="corr-live-prod",
        stage=StageName.GATE,
        phase=StagePhase.DONE,
        ts=datetime(2026, 7, 15, 0, 0, tzinfo=UTC),
        detail={"tier": "t2", "gate_decision": "hil", "mode": "shadow"},
    ).to_dict()


async def test_relays_raw_stage_event_to_live_sse_channel() -> None:
    bus = InMemoryEventBus()
    sink = InMemorySseSink()
    topic = "aw.pipeline.stages"
    channel = "aw.pipeline.stages"
    await bus.publish(topic, "evt-live-prod", _frame())
    publisher = SseSinkStagePublisher(sink, channel=channel)
    broadcaster = LiveStageBroadcaster(
        event_bus=bus,
        publisher=publisher,
        stage_topic=topic,
    )

    subscription = sink.subscribe(channel)
    next_event = asyncio.create_task(anext(subscription))
    await _drain(broadcaster)
    sse = await asyncio.wait_for(next_event, timeout=5.0)
    await subscription.aclose()

    assert sse.event == "stage"
    assert sse.id == "evt-live-prod"
    assert '"correlation_id":"corr-live-prod"' in sse.data
    assert '"gate_decision":"hil"' in sse.data
    assert '"payload"' not in sse.data


async def test_drops_malformed_stage_frame_and_continues() -> None:
    bus = InMemoryEventBus()
    sink = InMemorySseSink()
    topic = "aw.pipeline.stages"
    channel = "aw.pipeline.stages"
    await bus.publish(topic, "bad", {"not": "a stage frame"})
    await bus.publish(topic, "evt-live-prod", _frame())
    broadcaster = LiveStageBroadcaster(
        event_bus=bus,
        publisher=SseSinkStagePublisher(sink, channel=channel),
        stage_topic=topic,
    )

    subscription = sink.subscribe(channel)
    next_event = asyncio.create_task(anext(subscription))
    await _drain(broadcaster)
    sse = await asyncio.wait_for(next_event, timeout=5.0)
    await subscription.aclose()

    assert sse.id == "evt-live-prod"


async def test_run_after_stop_raises() -> None:
    broadcaster = LiveStageBroadcaster(
        event_bus=InMemoryEventBus(),
        publisher=SseSinkStagePublisher(InMemorySseSink(), channel="live"),
    )
    await broadcaster.stop()

    try:
        await broadcaster.run()
    except RuntimeError as error:
        assert "already stopped" in str(error)
    else:
        raise AssertionError("run after stop MUST fail closed")


def test_config_rejects_invalid_retry_backoff() -> None:
    for invalid_backoff in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="retry_backoff_seconds MUST be finite and positive"):
            LiveStageBroadcaster(
                event_bus=InMemoryEventBus(),
                publisher=SseSinkStagePublisher(InMemorySseSink(), channel="live"),
                retry_backoff_seconds=invalid_backoff,
            )
