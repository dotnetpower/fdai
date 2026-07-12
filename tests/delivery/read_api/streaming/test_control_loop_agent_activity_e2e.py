"""End-to-end: a real dev ControlLoop drives the agent-activity channel (Phase 4C).

Starts the dev :class:`ControlLoopLiveEmitter` with the agent-activity relay
wired as its ``stage_publisher_wrapper`` and asserts that real pipeline stage
frames surface as ``agent.state`` / ``incident.ticket`` events. Skips when the
shipped rule catalog cannot be composed in this environment.
"""

from __future__ import annotations

import asyncio

import pytest

from fdai.delivery.read_api.streaming.agent_activity_relay import (
    ControlLoopAgentActivityRelay,
)
from fdai.delivery.read_api.streaming.agent_activity_stream import (
    AgentActivityEvent,
    AgentStateEvent,
    IncidentTicketEvent,
)
from fdai.delivery.read_api.streaming.live_control_loop import (
    ControlLoopEmitterUnavailable,
    build_control_loop_emitter,
)
from fdai.shared.providers.stage_publisher import StagePublisher
from fdai.shared.providers.testing.sse import InMemorySseSink


class _RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[AgentActivityEvent] = []

    async def publish(self, event: AgentActivityEvent) -> None:
        self.events.append(event)


async def test_real_control_loop_drives_agent_activity() -> None:
    recorder = _RecordingPublisher()

    def _wrapper(inner: StagePublisher) -> StagePublisher:
        return ControlLoopAgentActivityRelay(publisher=recorder, inner=inner)

    emitter = build_control_loop_emitter(
        InMemorySseSink(),
        "aw.pipeline.stages",
        events_per_second=20.0,
        stage_publisher_wrapper=_wrapper,
    )
    try:
        await emitter.start()
    except ControlLoopEmitterUnavailable:
        pytest.skip("rule catalog not composable in this environment")

    try:
        # Wait (bounded) for the pump to produce real agent-activity frames.
        deadline = asyncio.get_running_loop().time() + 5.0
        while asyncio.get_running_loop().time() < deadline:
            has_state = any(isinstance(e, AgentStateEvent) for e in recorder.events)
            has_ticket = any(isinstance(e, IncidentTicketEvent) for e in recorder.events)
            if has_state and has_ticket:
                break
            await asyncio.sleep(0.05)
    finally:
        await emitter.stop()

    assert any(isinstance(e, AgentStateEvent) for e in recorder.events), (
        "the real pipeline MUST surface agent.state frames on the relay"
    )
    assert any(isinstance(e, IncidentTicketEvent) for e in recorder.events), (
        "the real pipeline MUST surface incident.ticket frames on the relay"
    )
    # Every relayed agent is a real pantheon name (never the 'unknown' sentinel
    # for a mapped pipeline stage).
    agents = {e.agent for e in recorder.events if isinstance(e, AgentStateEvent)}
    assert "Huginn" in agents  # ingest always fires first
