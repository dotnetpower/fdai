"""Tests for the production-path agent-activity broadcaster + parser (Phase 4)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from fdai.delivery.read_api.streaming.agent_activity_broadcaster import (
    AgentActivityBroadcaster,
    parse_stage_event,
)
from fdai.delivery.read_api.streaming.agent_activity_stream import (
    AgentActivityEvent,
    AgentStateEvent,
    IncidentTicketEvent,
)
from fdai.shared.providers.stage_publisher import (
    ObservationSource,
    StageEvent,
    StageName,
    StagePhase,
)
from fdai.shared.providers.testing.event_bus import InMemoryEventBus

_TS = datetime(2026, 7, 12, 9, 0, 0, tzinfo=UTC)


def _stage_dict(
    stage: StageName = StageName.INGEST,
    phase: StagePhase = StagePhase.DONE,
    *,
    correlation_id: str = "corr-1",
    detail: dict[str, object] | None = None,
    error: str | None = None,
) -> dict[str, object]:
    return StageEvent(
        event_id="evt-1",
        correlation_id=correlation_id,
        stage=stage,
        phase=phase,
        ts=_TS,
        detail=detail or {},
        error=error,
    ).to_dict()


class _RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[AgentActivityEvent] = []

    async def publish(self, event: AgentActivityEvent) -> None:
        self.events.append(event)


# ---------------------------------------------------------------------------
# parse_stage_event - inverse of StageEvent.to_dict, fail-closed
# ---------------------------------------------------------------------------


class TestParseStageEvent:
    def test_round_trips_a_real_stage_event(self) -> None:
        original = StageEvent(
            event_id="e1",
            correlation_id="c1",
            stage=StageName.GATE,
            phase=StagePhase.DONE,
            ts=_TS,
            detail={"gate_decision": "hil", "tier": "t0"},
        )
        parsed = parse_stage_event(original.to_dict())
        assert parsed == original

    def test_round_trips_a_failed_frame_with_error(self) -> None:
        original = StageEvent(
            event_id="e1",
            correlation_id="c1",
            stage=StageName.EXECUTE,
            phase=StagePhase.FAILED,
            ts=_TS,
            error="lock timeout",
        )
        assert parse_stage_event(original.to_dict()) == original

    def test_missing_field_is_none(self) -> None:
        payload = _stage_dict()
        del payload["correlation_id"]
        assert parse_stage_event(payload) is None

    def test_unknown_stage_is_none(self) -> None:
        payload = _stage_dict()
        payload["stage"] = "teleport"
        assert parse_stage_event(payload) is None

    def test_unknown_phase_is_none(self) -> None:
        payload = _stage_dict()
        payload["phase"] = "vibing"
        assert parse_stage_event(payload) is None

    def test_naive_timestamp_is_none(self) -> None:
        payload = _stage_dict()
        payload["ts"] = "2026-07-12T09:00:00"  # no tz offset
        assert parse_stage_event(payload) is None

    def test_non_string_id_is_none(self) -> None:
        payload = _stage_dict()
        payload["event_id"] = 42
        assert parse_stage_event(payload) is None

    def test_failed_without_error_violates_invariant_and_is_none(self) -> None:
        # phase=failed but no error string -> StageEvent.__post_init__ raises,
        # so the parser fails closed.
        payload = _stage_dict(phase=StagePhase.DONE)
        payload["phase"] = "failed"  # now phase=failed with no error
        assert parse_stage_event(payload) is None

    def test_bad_detail_type_is_none(self) -> None:
        payload = _stage_dict()
        payload["detail"] = ["not", "a", "mapping"]
        assert parse_stage_event(payload) is None

    def test_non_string_error_is_none(self) -> None:
        payload = _stage_dict()
        payload["error"] = 123  # non-string error field
        assert parse_stage_event(payload) is None

    def test_legacy_and_unknown_sources_normalize_without_dropping_frame(self) -> None:
        original = StageEvent(
            event_id="e1",
            correlation_id="c1",
            stage=StageName.ROUTE,
            phase=StagePhase.DONE,
            ts=_TS,
        )
        legacy = original.to_dict()
        legacy.pop("source")
        assert parse_stage_event(legacy).source is ObservationSource.UNKNOWN
        future = {**original.to_dict(), "source": "future-source"}
        assert parse_stage_event(future).source is ObservationSource.UNKNOWN


# ---------------------------------------------------------------------------
# AgentActivityBroadcaster
# ---------------------------------------------------------------------------


async def _drain(broadcaster: AgentActivityBroadcaster) -> None:
    """Run the broadcaster until the in-memory topic snapshot is exhausted."""
    await broadcaster.run()
    task = broadcaster._task
    assert task is not None
    await asyncio.wait_for(task, timeout=5.0)
    await broadcaster.stop()


async def test_consumes_stage_frames_and_publishes_agent_activity() -> None:
    bus = InMemoryEventBus()
    topic = "aw.pipeline.stages"
    for frame in (
        _stage_dict(StageName.INGEST, detail={"incident_id": "incident-1"}),
        _stage_dict(StageName.GATE, detail={"gate_decision": "auto"}),
        _stage_dict(
            StageName.AUDIT,
            StagePhase.DONE,
            detail={"outcome": "executed", "decision": "auto"},
        ),
    ):
        await bus.publish(topic, "evt-1", frame)

    pub = _RecordingPublisher()
    broadcaster = AgentActivityBroadcaster(event_bus=bus, publisher=pub, stage_topic=topic)
    await _drain(broadcaster)

    assert any(isinstance(e, AgentStateEvent) for e in pub.events)
    tickets = [e for e in pub.events if isinstance(e, IncidentTicketEvent)]
    assert tickets[-1].status.value == "resolved"
    assert "Huginn" in {e.agent for e in pub.events if isinstance(e, AgentStateEvent)}


async def test_routine_stage_frames_do_not_fabricate_incident_tickets() -> None:
    bus = InMemoryEventBus()
    topic = "aw.pipeline.stages"
    await bus.publish(topic, "evt-1", _stage_dict(StageName.INGEST))

    pub = _RecordingPublisher()
    broadcaster = AgentActivityBroadcaster(event_bus=bus, publisher=pub, stage_topic=topic)
    await _drain(broadcaster)

    assert any(isinstance(event, AgentStateEvent) for event in pub.events)
    assert not any(isinstance(event, IncidentTicketEvent) for event in pub.events)


async def test_malformed_frames_are_dropped() -> None:
    bus = InMemoryEventBus()
    topic = "aw.pipeline.stages"
    await bus.publish(topic, "k", {"not": "a stage frame"})
    await bus.publish(topic, "k", _stage_dict(StageName.INGEST))

    pub = _RecordingPublisher()
    broadcaster = AgentActivityBroadcaster(event_bus=bus, publisher=pub, stage_topic=topic)
    await _drain(broadcaster)

    # Only the one valid frame produced output; the malformed one was dropped.
    assert any(isinstance(e, AgentStateEvent) for e in pub.events)
    agents = {e.agent for e in pub.events if isinstance(e, AgentStateEvent)}
    assert agents == {"Huginn"}


async def test_publish_failure_does_not_kill_the_relay() -> None:
    class _Raising:
        async def publish(self, event: AgentActivityEvent) -> None:
            raise RuntimeError("sink down")

    bus = InMemoryEventBus()
    topic = "aw.pipeline.stages"
    await bus.publish(topic, "k", _stage_dict(StageName.INGEST))
    broadcaster = AgentActivityBroadcaster(event_bus=bus, publisher=_Raising(), stage_topic=topic)
    await _drain(broadcaster)  # must not raise


async def test_run_is_idempotent() -> None:
    bus = InMemoryEventBus()
    pub = _RecordingPublisher()
    broadcaster = AgentActivityBroadcaster(event_bus=bus, publisher=pub)
    await broadcaster.run()
    await broadcaster.run()  # second call is a no-op
    await broadcaster.stop()


async def test_stop_before_run_is_safe() -> None:
    bus = InMemoryEventBus()
    pub = _RecordingPublisher()
    broadcaster = AgentActivityBroadcaster(event_bus=bus, publisher=pub)
    await broadcaster.stop()  # idempotent, nothing started


async def test_stop_is_idempotent() -> None:
    bus = InMemoryEventBus()
    pub = _RecordingPublisher()
    broadcaster = AgentActivityBroadcaster(event_bus=bus, publisher=pub)
    await broadcaster.run()
    await broadcaster.stop()
    await broadcaster.stop()  # second stop is a no-op


async def test_stop_cancels_a_still_running_relay() -> None:
    # A relay blocked on subscribe() must cancel cleanly on stop().
    class _BlockingBus(InMemoryEventBus):
        def subscribe(self, topic: str, group_id: str):  # type: ignore[override]
            async def _gen():
                await asyncio.Event().wait()  # blocks until cancelled
                yield  # pragma: no cover

            return _gen()

    broadcaster = AgentActivityBroadcaster(
        event_bus=_BlockingBus(), publisher=_RecordingPublisher()
    )
    await broadcaster.run()
    await asyncio.sleep(0)  # let the relay task reach the blocking await
    await broadcaster.stop()  # must cancel the task and return cleanly


async def test_run_after_stop_raises() -> None:
    # stop() marks the broadcaster spent; a subsequent run() (before any prior
    # run set _started) fails closed rather than silently resurrecting it.
    bus = InMemoryEventBus()
    pub = _RecordingPublisher()
    broadcaster = AgentActivityBroadcaster(event_bus=bus, publisher=pub)
    await broadcaster.stop()
    with pytest.raises(RuntimeError, match="already stopped"):
        await broadcaster.run()


async def test_run_after_start_and_stop_raises() -> None:
    """Regression: run()->stop()->run() MUST raise, not silently no-op.

    A prior implementation checked `_started` before `_stopped`, so after the
    start->stop cycle a second run() saw `_started=True` and returned silently,
    making the RuntimeError guard unreachable.
    """
    bus = InMemoryEventBus()
    pub = _RecordingPublisher()
    broadcaster = AgentActivityBroadcaster(event_bus=bus, publisher=pub)
    await broadcaster.run()
    await asyncio.sleep(0)
    await broadcaster.stop()
    with pytest.raises(RuntimeError, match="already stopped"):
        await broadcaster.run()


def test_config_guards() -> None:
    bus = InMemoryEventBus()
    pub = _RecordingPublisher()
    with pytest.raises(ValueError, match="stage_topic MUST be non-empty"):
        AgentActivityBroadcaster(event_bus=bus, publisher=pub, stage_topic="")
    with pytest.raises(ValueError, match="group_id MUST be non-empty"):
        AgentActivityBroadcaster(event_bus=bus, publisher=pub, group_id="")
    with pytest.raises(ValueError, match="max_incidents MUST be positive"):
        AgentActivityBroadcaster(event_bus=bus, publisher=pub, max_incidents=0)
    for invalid_backoff in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="retry_backoff_seconds MUST be finite and positive"):
            AgentActivityBroadcaster(
                event_bus=bus,
                publisher=pub,
                retry_backoff_seconds=invalid_backoff,
            )


async def test_transient_bus_error_is_retried_then_recovers() -> None:
    calls = {"n": 0}

    class _FlakyBus(InMemoryEventBus):
        def subscribe(self, topic: str, group_id: str):  # type: ignore[override]
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("broker blip")
            return super().subscribe(topic, group_id)

    bus = _FlakyBus()
    topic = "aw.pipeline.stages"
    await bus.publish(topic, "k", _stage_dict(StageName.INGEST))
    pub = _RecordingPublisher()
    sleeps: list[float] = []

    async def _sleeper(s: float) -> None:
        sleeps.append(s)

    broadcaster = AgentActivityBroadcaster(
        event_bus=bus, publisher=pub, stage_topic=topic, sleeper=_sleeper
    )
    await _drain(broadcaster)
    assert sleeps, "a transient error MUST trigger a backoff sleep"
    assert any(isinstance(e, AgentStateEvent) for e in pub.events)
