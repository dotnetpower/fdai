"""Tests for the real-path agent-activity relay (Phase 4B)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.delivery.read_api.streaming.agent_activity_relay import (
    ControlLoopAgentActivityRelay,
)
from fdai.delivery.read_api.streaming.agent_activity_stream import (
    AgentActivityEvent,
    AgentStateEvent,
    IncidentTicketEvent,
)
from fdai.shared.providers.stage_publisher import StageEvent, StageName, StagePhase

_TS = datetime(2026, 7, 12, 9, 0, 0, tzinfo=UTC)


class _RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[AgentActivityEvent] = []

    async def publish(self, event: AgentActivityEvent) -> None:
        self.events.append(event)


class _RecordingStagePublisher:
    def __init__(self) -> None:
        self.events: list[StageEvent] = []

    async def emit(self, event: StageEvent) -> None:
        self.events.append(event)


class _RaisingPublisher:
    async def publish(self, event: AgentActivityEvent) -> None:
        raise RuntimeError("sink down")


class _RaisingStagePublisher:
    async def emit(self, event: StageEvent) -> None:
        raise RuntimeError("inner down")


def _stage(
    stage: StageName,
    phase: StagePhase = StagePhase.BEGIN,
    *,
    correlation_id: str = "corr-1",
    detail: dict[str, object] | None = None,
) -> StageEvent:
    return StageEvent(
        event_id="evt-1",
        correlation_id=correlation_id,
        stage=stage,
        phase=phase,
        ts=_TS,
        detail=detail or {},
    )


async def test_projects_and_publishes_agent_activity() -> None:
    pub = _RecordingPublisher()
    relay = ControlLoopAgentActivityRelay(publisher=pub)
    await relay.emit(_stage(StageName.INGEST))
    kinds = {type(e) for e in pub.events}
    assert IncidentTicketEvent in kinds
    assert AgentStateEvent in kinds
    state = next(e for e in pub.events if isinstance(e, AgentStateEvent))
    assert state.agent == "Huginn"


async def test_tees_every_frame_to_the_inner_publisher() -> None:
    pub = _RecordingPublisher()
    inner = _RecordingStagePublisher()
    relay = ControlLoopAgentActivityRelay(publisher=pub, inner=inner)
    await relay.emit(_stage(StageName.INGEST))
    await relay.emit(_stage(StageName.AUDIT, StagePhase.DONE))
    # The live cockpit still sees the raw stage frames unchanged.
    assert len(inner.events) == 2
    assert inner.events[0].stage is StageName.INGEST


async def test_full_incident_resolves() -> None:
    pub = _RecordingPublisher()
    relay = ControlLoopAgentActivityRelay(publisher=pub)
    for stage, phase in [
        (StageName.INGEST, StagePhase.BEGIN),
        (StageName.GATE, StagePhase.BEGIN),
        (StageName.EXECUTE, StagePhase.BEGIN),
        (StageName.AUDIT, StagePhase.DONE),
    ]:
        detail = {"outcome": "executed"} if stage is StageName.AUDIT else None
        await relay.emit(_stage(stage, phase, detail=detail))
    tickets = [e for e in pub.events if isinstance(e, IncidentTicketEvent)]
    assert tickets[-1].status.value == "resolved"


async def test_inner_failure_is_swallowed_and_still_publishes() -> None:
    # A broken live-cockpit publisher MUST NOT stop the agent-activity relay.
    pub = _RecordingPublisher()
    relay = ControlLoopAgentActivityRelay(publisher=pub, inner=_RaisingStagePublisher())
    await relay.emit(_stage(StageName.INGEST))
    assert len(pub.events) >= 1


async def test_publish_failure_is_swallowed() -> None:
    # A slow / disconnected agent-activity sink MUST NOT raise into the pipeline.
    relay = ControlLoopAgentActivityRelay(publisher=_RaisingPublisher())
    await relay.emit(_stage(StageName.INGEST))  # must not raise


async def test_state_is_bounded_by_max_incidents() -> None:
    pub = _RecordingPublisher()
    relay = ControlLoopAgentActivityRelay(publisher=pub, max_incidents=3)
    for i in range(10):
        await relay.emit(_stage(StageName.INGEST, correlation_id=f"corr-{i}"))
    # Only the most recent 3 correlations are retained.
    assert len(relay._projection.incidents) == 3
    assert set(relay._projection.incidents) == {"corr-7", "corr-8", "corr-9"}


def test_rejects_non_positive_max_incidents() -> None:
    with pytest.raises(ValueError, match="max_incidents MUST be positive"):
        ControlLoopAgentActivityRelay(publisher=_RecordingPublisher(), max_incidents=0)


async def test_concurrent_emits_fold_without_loss() -> None:
    import asyncio

    pub = _RecordingPublisher()
    relay = ControlLoopAgentActivityRelay(publisher=pub)
    await asyncio.gather(
        *(relay.emit(_stage(StageName.INGEST, correlation_id=f"c-{i}")) for i in range(20))
    )
    assert len(relay._projection.incidents) == 20
