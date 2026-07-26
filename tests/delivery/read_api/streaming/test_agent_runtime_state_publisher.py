"""Tests for health-derived Pantheon runtime-state publication."""

from __future__ import annotations

import pytest

from fdai.agents import AgentHandlerPhase
from fdai.delivery.read_api.streaming.agent_activity_stream import (
    runtime_agent_state_snapshot,
)
from fdai.delivery.read_api.streaming.agent_runtime_state_publisher import (
    AgentRuntimeStatePublisher,
    EventBusPantheonActivityObserver,
)
from fdai.shared.providers.testing.event_bus import InMemoryEventBus


async def test_publishes_observed_state_for_every_live_agent() -> None:
    event_bus = InMemoryEventBus()
    health = {
        "consumers_live": 2,
        "agent_health": {
            "Odin": {"status": "ok"},
            "Huginn": {"status": "ok"},
        },
    }
    publisher = AgentRuntimeStatePublisher(
        event_bus=event_bus,
        snapshot_factory=lambda: runtime_agent_state_snapshot(health),
    )

    assert await publisher.publish_once() == 2
    payloads = [
        envelope.payload
        async for envelope in event_bus.subscribe("aw.pipeline.stages", "test-reader")
    ]

    assert [payload["agent"] for payload in payloads] == ["Odin", "Huginn"]
    assert [payload["state"] for payload in payloads] == ["idle", "watching"]
    assert all(payload["type"] == "agent.runtime-state" for payload in payloads)
    assert all(payload["source"] == "runtime-observed" for payload in payloads)


async def test_does_not_publish_when_consumers_are_not_live() -> None:
    event_bus = InMemoryEventBus()
    publisher = AgentRuntimeStatePublisher(
        event_bus=event_bus,
        snapshot_factory=lambda: runtime_agent_state_snapshot(
            {
                "consumers_live": 0,
                "agent_health": {"Odin": {"status": "ok"}},
            }
        ),
    )

    assert await publisher.publish_once() == 0


async def test_does_not_publish_agents_with_terminal_consumers() -> None:
    event_bus = InMemoryEventBus()
    publisher = AgentRuntimeStatePublisher(
        event_bus=event_bus,
        snapshot_factory=lambda: runtime_agent_state_snapshot(
            {
                "consumers_live": 2,
                "unavailable_agents": ["Huginn"],
                "agent_health": {
                    "Odin": {"status": "ok"},
                    "Huginn": {"status": "ok"},
                },
            }
        ),
    )

    assert await publisher.publish_once() == 1
    payloads = [
        envelope.payload
        async for envelope in event_bus.subscribe("aw.pipeline.stages", "test-reader")
    ]
    assert [payload["agent"] for payload in payloads] == ["Odin"]


async def test_publishes_real_handler_lifecycle_to_shared_stage_topic() -> None:
    event_bus = InMemoryEventBus()
    observer = EventBusPantheonActivityObserver(event_bus=event_bus)
    payload = {
        "correlation_id": "corr-1",
        "ts": "2026-07-24T04:00:00+00:00",
    }

    await observer.observe(
        agent="Forseti",
        topic="object.anomaly",
        phase=AgentHandlerPhase.STARTED,
        payload=payload,
    )
    await observer.observe(
        agent="Forseti",
        topic="object.anomaly",
        phase=AgentHandlerPhase.COMPLETED,
        payload=payload,
    )
    await observer.observe(
        agent="Thor",
        topic="object.verdict",
        phase=AgentHandlerPhase.FAILED,
        payload=payload,
        error_type="RuntimeError",
    )
    frames = [
        envelope.payload
        async for envelope in event_bus.subscribe("aw.pipeline.stages", "test-reader")
    ]

    assert [frame["agent"] for frame in frames] == ["Forseti", "Forseti", "Thor"]
    assert [frame["state"] for frame in frames] == ["deciding", "idle", "idle"]
    assert [frame["detail"] for frame in frames] == [
        "Processing object.anomaly",
        "Processed object.anomaly",
        "Failed object.verdict (RuntimeError)",
    ]
    assert frames[0]["correlation_id"] == "corr-1"
    assert frames[1]["correlation_id"] is None
    assert all(frame["type"] == "agent.runtime-state" for frame in frames)
    assert all(frame["source"] == "runtime-observed" for frame in frames)


@pytest.mark.parametrize("interval", [0.0, -1.0, float("nan"), float("inf")])
def test_rejects_invalid_configuration(interval: float) -> None:
    with pytest.raises(ValueError, match="interval_seconds MUST be finite and positive"):
        AgentRuntimeStatePublisher(
            event_bus=InMemoryEventBus(),
            snapshot_factory=tuple,
            interval_seconds=interval,
        )
