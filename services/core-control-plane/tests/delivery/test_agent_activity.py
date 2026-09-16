from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fdai.delivery.agent_activity import (
    AgentRuntimeStatePublisher,
    AgentState,
    AgentStateEvent,
    EventBusPantheonActivityObserver,
    runtime_agent_state_snapshot,
)


class RecordingEventBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, dict[str, object]]] = []

    async def publish(
        self,
        topic: str,
        producer_principal: str,
        payload: dict[str, object],
    ) -> None:
        self.published.append((topic, producer_principal, payload))


class ConcurrentRecordingEventBus(RecordingEventBus):
    def __init__(self) -> None:
        super().__init__()
        self.active = 0
        self.max_active = 0

    async def publish(
        self,
        topic: str,
        producer_principal: str,
        payload: dict[str, object],
    ) -> None:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0)
        await super().publish(topic, producer_principal, payload)
        self.active -= 1


def _health(agent: str) -> dict[str, object]:
    return {
        "consumers_live": 1,
        "agent_health": {agent: {"status": "ok"}},
        "unavailable_agents": [],
    }


async def test_periodic_snapshot_preserves_active_handler_state() -> None:
    observer = EventBusPantheonActivityObserver(event_bus=RecordingEventBus())
    payload = {"correlation_id": "correlation-1"}

    await observer.observe(
        agent="Huginn",
        topic="object.event",
        phase=SimpleNamespace(value="started"),
        payload=payload,
    )

    snapshot = runtime_agent_state_snapshot(
        _health("Huginn"),
        active_states=observer.active_states(),
    )

    assert len(snapshot) == 1
    assert snapshot[0].state is AgentState.COLLECTING
    assert snapshot[0].correlation_id == "correlation-1"
    assert snapshot[0].detail == "Processing object.event"


async def test_completing_one_topic_preserves_other_active_handler() -> None:
    observer = EventBusPantheonActivityObserver(event_bus=RecordingEventBus())
    first = {"correlation_id": "correlation-1"}
    second = {"correlation_id": "correlation-2"}

    await observer.observe(
        agent="Heimdall",
        topic="object.event",
        phase=SimpleNamespace(value="started"),
        payload=first,
    )
    await observer.observe(
        agent="Heimdall",
        topic="object.action-run",
        phase=SimpleNamespace(value="started"),
        payload=second,
    )
    await observer.observe(
        agent="Heimdall",
        topic="object.action-run",
        phase=SimpleNamespace(value="completed"),
        payload=second,
    )

    active = observer.active_states()

    assert active["Heimdall"].state is AgentState.ANALYZING
    assert active["Heimdall"].correlation_id == "correlation-1"
    assert active["Heimdall"].detail == "Processing object.event"


async def test_periodic_snapshot_publishes_agent_states_concurrently() -> None:
    event_bus = ConcurrentRecordingEventBus()
    publisher = AgentRuntimeStatePublisher(
        event_bus=event_bus,
        snapshot_factory=lambda: (
            AgentStateEvent(agent="Huginn", state=AgentState.WATCHING, ts="2026-01-01T00:00:00Z"),
            AgentStateEvent(agent="Heimdall", state=AgentState.IDLE, ts="2026-01-01T00:00:00Z"),
        ),
    )

    assert await publisher.publish_once() == 2
    assert event_bus.max_active == 2
    assert {principal for _, principal, _ in event_bus.published} == {"Huginn", "Heimdall"}
