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
    payload = {
        "event_id": "event-1",
        "correlation_id": "correlation-1",
        "resource_id": "resource-1",
    }

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
    assert snapshot[0].activity is not None
    assert snapshot[0].activity.activity_id
    assert snapshot[0].activity.resource_ref == "resource-1"


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


async def test_handler_transitions_preserve_bounded_resource_context() -> None:
    event_bus = RecordingEventBus()
    observer = EventBusPantheonActivityObserver(event_bus=event_bus)
    payload = {
        "event_id": "event-1",
        "idempotency_key": "event-key-1",
        "correlation_id": "correlation-1",
        "event_type": "inventory.resource_changed",
        "resource_id": "scope:example/resource-group/example/providers/compute/vm-example",
        "resource_type": "compute-vm",
    }

    await observer.observe(
        agent="Huginn",
        topic="fdai.change.events",
        phase=SimpleNamespace(value="started"),
        payload=payload,
    )
    await observer.observe(
        agent="Huginn",
        topic="fdai.change.events",
        phase=SimpleNamespace(value="completed"),
        payload=payload,
    )

    started = event_bus.published[0][2]
    completed = event_bus.published[1][2]
    assert started["activity_id"] == completed["activity_id"]
    assert completed["correlation_id"] is None
    assert completed["activity_correlation_id"] == "correlation-1"
    assert started["phase"] == "started"
    assert completed["phase"] == "completed"
    assert completed["resource_ref"] == payload["resource_id"]
    assert completed["resource_name"] == "vm-example"
    assert completed["resource_type"] == "compute-vm"
    assert completed["event_type"] == "inventory.resource_changed"
    assert completed["event_id"] == "event-1"
    assert completed["started_at"] == started["started_at"]
    assert started["ts"] == started["started_at"]
    assert completed["ts"] == completed["completed_at"]
    assert completed["completed_at"] >= completed["started_at"]
    assert isinstance(completed["duration_ms"], int)


async def test_handler_transition_without_identity_remains_legacy_state() -> None:
    event_bus = RecordingEventBus()
    observer = EventBusPantheonActivityObserver(event_bus=event_bus)

    await observer.observe(
        agent="Huginn",
        topic="fdai.change.events",
        phase=SimpleNamespace(value="started"),
        payload={"resource_id": "resource-1"},
    )

    published = event_bus.published[0][2]
    assert published["detail"] == "Processing fdai.change.events"
    assert "activity_id" not in published
    assert "phase" not in published
    assert "resource_ref" not in published


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
