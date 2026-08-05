"""Pantheon handler lifecycle to agent-activity projection tests."""

from __future__ import annotations

from fdai.agents import AgentHandlerPhase
from fdai.delivery.agent_activity import EventBusPantheonActivityObserver
from fdai.delivery.operator_api.streaming.agent_activity_stream import (
    AgentActivityEvent,
    AgentState,
    AgentStateEvent,
)
from fdai.delivery.operator_api.streaming.pantheon_activity_observer import (
    PantheonActivityObserver,
)
from fdai.shared.providers.stage_publisher import ObservationSource
from fdai.shared.providers.testing.event_bus import InMemoryEventBus


class RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[AgentActivityEvent] = []

    async def publish(self, event: AgentActivityEvent) -> None:
        self.events.append(event)


async def test_projects_huginn_and_heimdall_handler_lifecycle() -> None:
    publisher = RecordingPublisher()
    observer = PantheonActivityObserver(publisher=publisher)

    for agent, topic in (("Huginn", "aw.events"), ("Heimdall", "object.event")):
        await observer.observe(
            agent=agent,
            topic=topic,
            phase=AgentHandlerPhase.STARTED,
            payload={"correlation_id": "corr-live"},
        )
        await observer.observe(
            agent=agent,
            topic=topic,
            phase=AgentHandlerPhase.COMPLETED,
            payload={"correlation_id": "corr-live"},
        )

    state_events = [event for event in publisher.events if isinstance(event, AgentStateEvent)]
    assert [(event.agent, event.state) for event in state_events] == [
        ("Huginn", AgentState.COLLECTING),
        ("Huginn", AgentState.WATCHING),
        ("Heimdall", AgentState.ANALYZING),
        ("Heimdall", AgentState.WATCHING),
    ]
    assert [event.correlation_id for event in state_events] == [
        "corr-live",
        None,
        "corr-live",
        None,
    ]
    assert all(event.source is ObservationSource.RUNTIME_OBSERVED for event in state_events)


async def test_http_and_event_bus_observers_share_the_same_projection() -> None:
    publisher = RecordingPublisher()
    http_observer = PantheonActivityObserver(publisher=publisher)
    event_bus = InMemoryEventBus()
    bus_observer = EventBusPantheonActivityObserver(event_bus=event_bus)
    payload = {
        "correlation_id": "corr-parity",
        "ts": "2026-07-24T04:00:00+00:00",
    }

    await http_observer.observe(
        agent="Forseti",
        topic="object.anomaly",
        phase=AgentHandlerPhase.STARTED,
        payload=payload,
    )
    await bus_observer.observe(
        agent="Forseti",
        topic="object.anomaly",
        phase=AgentHandlerPhase.STARTED,
        payload=payload,
    )
    bus_frames = [
        envelope.payload
        async for envelope in event_bus.subscribe("aw.pipeline.stages", "test-reader")
    ]

    assert len(publisher.events) == 1
    assert isinstance(publisher.events[0], AgentStateEvent)
    assert bus_frames == [publisher.events[0].to_runtime_payload()]
