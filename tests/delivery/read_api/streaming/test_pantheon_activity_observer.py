"""Pantheon handler lifecycle to agent-activity projection tests."""

from __future__ import annotations

from fdai.agents import AgentHandlerPhase
from fdai.delivery.read_api.streaming.agent_activity_stream import (
    AgentActivityEvent,
    AgentState,
    AgentStateEvent,
)
from fdai.delivery.read_api.streaming.pantheon_activity_observer import (
    PantheonActivityObserver,
)
from fdai.shared.providers.stage_publisher import ObservationSource


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
