"""Tests for the agent-activity SSE surface (Track B, Phase 1).

Split by concern:

- ``TestWireEncoding`` - the three semantic events serialize to the
  documented JSON payloads.
- ``TestConfig`` - dataclass validation.
- ``TestPublisher`` - one event fans out through ``InMemorySseSink``.
- ``TestSyntheticEmitter`` - the heartbeat + incident narrative publishes
  the expected event kinds and ticket lifecycle on the channel.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from fdai.delivery.read_api.streaming.agent_activity_emitter import (
    _ALL_AGENTS,
    _SCENARIOS,
    SyntheticAgentActivityEmitter,
)
from fdai.delivery.read_api.streaming.agent_activity_stream import (
    AgentActivityStreamConfig,
    AgentState,
    AgentStateEvent,
    ConversationTurnEvent,
    IncidentTicketEvent,
    SseAgentActivityPublisher,
    TicketStatus,
    TurnKind,
    runtime_agent_state_snapshot,
)
from fdai.shared.providers.stage_publisher import ObservationSource
from fdai.shared.providers.testing.sse import InMemorySseSink


class TestWireEncoding:
    def test_agent_state_payload(self) -> None:
        ev = AgentStateEvent(
            agent="Heimdall", state=AgentState.WATCHING, ts="2026-07-12T00:00:00+00:00"
        )
        payload = json.loads(ev.to_sse_event().data)
        assert payload["type"] == "agent.state"
        assert payload["agent"] == "Heimdall"
        assert payload["state"] == "watching"
        assert payload["correlation_id"] is None

    def test_incident_ticket_payload(self) -> None:
        ev = IncidentTicketEvent(
            ticket_id="FDAI-1234",
            correlation_id="incident-abc",
            status=TicketStatus.OPEN,
            title="t",
            severity="high",
            involved_agents=("Heimdall", "Forseti"),
            ts="2026-07-12T00:00:00+00:00",
        )
        payload = json.loads(ev.to_sse_event().data)
        assert payload["type"] == "incident.ticket"
        assert payload["status"] == "open"
        assert payload["involved_agents"] == ["Heimdall", "Forseti"]
        assert payload["rca"] is None

    def test_conversation_turn_payload(self) -> None:
        ev = ConversationTurnEvent(
            correlation_id="incident-abc",
            from_agent="Heimdall",
            to_agent="Forseti",
            kind=TurnKind.HANDOFF,
            text="anomaly 0.92",
            ts="2026-07-12T00:00:00+00:00",
        )
        payload = json.loads(ev.to_sse_event().data)
        assert payload["type"] == "conversation.turn"
        assert payload["from_agent"] == "Heimdall"
        assert payload["to_agent"] == "Forseti"
        assert payload["kind"] == "handoff"


class TestConfig:
    def test_defaults(self) -> None:
        cfg = AgentActivityStreamConfig()
        assert cfg.path == "/agents/stream"
        assert cfg.channel == "fdai.agents.events"

    def test_rejects_bad_path(self) -> None:
        with pytest.raises(ValueError, match="MUST start with"):
            AgentActivityStreamConfig(path="agents")

    def test_rejects_empty_channel(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            AgentActivityStreamConfig(channel="")

    def test_rejects_non_positive_keepalive(self) -> None:
        with pytest.raises(ValueError, match="keepalive_seconds"):
            AgentActivityStreamConfig(keepalive_seconds=0)

    def test_rejects_both_emitter_and_broadcaster(self) -> None:
        with pytest.raises(ValueError, match="at most one"):
            AgentActivityStreamConfig(
                emitter_factory=lambda _sink: None,
                broadcaster_factory=lambda _pub: None,  # type: ignore[arg-type,return-value]
            )


class TestRuntimeSnapshot:
    def test_projects_only_initialized_healthy_agents(self) -> None:
        events = runtime_agent_state_snapshot(
            {
                "consumers_live": 12,
                "agent_health": {
                    "Huginn": {"status": "ok"},
                    "Forseti": {"status": "ok"},
                    "Thor": {"status": "error"},
                },
            }
        )

        assert [(event.agent, event.state) for event in events] == [
            ("Huginn", AgentState.WATCHING),
            ("Forseti", AgentState.IDLE),
        ]
        assert all(event.source is ObservationSource.RUNTIME_OBSERVED for event in events)

    def test_returns_empty_snapshot_without_live_consumers(self) -> None:
        assert (
            runtime_agent_state_snapshot(
                {"consumers_live": 0, "agent_health": {"Huginn": {"status": "ok"}}}
            )
            == ()
        )


class TestBroadcasterWiring:
    """build_app starts a production broadcaster in the app lifespan."""

    def test_broadcaster_runs_and_stops_in_lifespan(self) -> None:
        import os

        from starlette.testclient import TestClient

        from fdai.delivery.read_api.auth import build_authenticator
        from fdai.delivery.read_api.main import ReadApiConfig, build_app
        from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
        from fdai.delivery.read_api.streaming.agent_activity_stream import (
            AgentActivityProducer,
        )
        from fdai.shared.providers.testing.sse import InMemorySseSink

        events: list[str] = []

        class _RecordingProducer:
            async def run(self) -> None:
                events.append("run")

            async def stop(self) -> None:
                events.append("stop")

        producer: AgentActivityProducer = _RecordingProducer()
        seen_publisher: list[object] = []

        def _factory(publisher: object) -> AgentActivityProducer:
            seen_publisher.append(publisher)
            return producer

        os.environ["FDAI_READ_API_DEV_MODE"] = "1"
        try:
            app = build_app(
                authenticator=build_authenticator(
                    verifier=lambda _t: {"oid": "u"}, resolver=lambda _c: None
                ),
                read_model=InMemoryConsoleReadModel(),
                config=ReadApiConfig(
                    dev_mode=True,
                    agent_activity=AgentActivityStreamConfig(
                        sink=InMemorySseSink(),
                        broadcaster_factory=_factory,
                    ),
                ),
            )
            # TestClient's context manager drives the ASGI lifespan.
            with TestClient(app):
                pass
        finally:
            os.environ.pop("FDAI_READ_API_DEV_MODE", None)

        assert events == ["run", "stop"]
        # The factory received the sink's publisher (an AgentActivityPublisher).
        assert len(seen_publisher) == 1
        assert hasattr(seen_publisher[0], "publish")


class TestPublisher:
    async def test_publish_fans_out_on_channel(self) -> None:
        sink = InMemorySseSink()
        pub = SseAgentActivityPublisher(sink=sink, channel="c")
        received: list[dict[str, object]] = []

        async def collect() -> None:
            async for ev in sink.subscribe("c"):
                received.append(json.loads(ev.data))
                return

        task = asyncio.create_task(collect())
        await asyncio.sleep(0)  # let the subscriber register
        await pub.publish(
            AgentStateEvent(agent="Odin", state=AgentState.IDLE, ts="2026-07-12T00:00:00+00:00")
        )
        await asyncio.wait_for(task, timeout=2.0)
        assert received[0]["agent"] == "Odin"


class TestSyntheticEmitter:
    def test_scenarios_cover_distinct_azure_operations(self) -> None:
        assert len(_SCENARIOS) == 9
        assert len({scenario.title for scenario in _SCENARIOS}) == 9
        assert {scenario.severity for scenario in _SCENARIOS} == {"low", "medium", "high"}
        assert all(scenario.involved and scenario.turns and scenario.rca for scenario in _SCENARIOS)

    async def test_incident_narrative_publishes_lifecycle(self) -> None:
        sink = InMemorySseSink()
        emitter = SyntheticAgentActivityEmitter(
            sink=sink,
            channel="c",
            incident_interval_seconds=0.02,
            beat_seconds=0.001,
            seed=7,
        )
        seen: list[dict[str, object]] = []

        async def collect() -> None:
            async for ev in sink.subscribe("c"):
                payload = json.loads(ev.data)
                seen.append(payload)
                if payload["type"] == "incident.ticket" and payload["status"] == "resolved":
                    return

        task = asyncio.create_task(collect())
        await asyncio.sleep(0)
        await emitter.start()
        try:
            await asyncio.wait_for(task, timeout=5.0)
        finally:
            await emitter.stop()

        kinds = {p["type"] for p in seen}
        assert kinds == {"agent.state", "incident.ticket", "conversation.turn"}
        # Ticket lifecycle: open -> ... -> resolved.
        ticket_statuses = [p["status"] for p in seen if p["type"] == "incident.ticket"]
        assert ticket_statuses[0] == "open"
        assert ticket_statuses[-1] == "resolved"
        assert "investigating" in ticket_statuses
        # RCA present on the resolved ticket.
        resolved = next(
            p for p in seen if p["type"] == "incident.ticket" and p["status"] == "resolved"
        )
        assert resolved["rca"]
        # At least one A2A conversation turn and an executing/approving state.
        assert any(p["type"] == "conversation.turn" for p in seen)
        states = {p["state"] for p in seen if p["type"] == "agent.state"}
        assert "executing" in states or "approving" in states

    async def test_late_subscriber_receives_periodic_agent_snapshot(self) -> None:
        sink = InMemorySseSink()
        emitter = SyntheticAgentActivityEmitter(
            sink=sink,
            channel="c",
            incident_interval_seconds=10.0,
            heartbeat_interval_seconds=0.01,
        )
        await emitter.start()
        await asyncio.sleep(0)
        seen: list[dict[str, object]] = []

        async def collect_snapshot() -> None:
            async for event in sink.subscribe("c"):
                payload = json.loads(event.data)
                if payload["type"] == "agent.state":
                    seen.append(payload)
                if len(seen) == 15:
                    return

        try:
            await asyncio.wait_for(collect_snapshot(), timeout=1.0)
        finally:
            await emitter.stop()

        assert {payload["agent"] for payload in seen} == set(_ALL_AGENTS)
        assert all(payload["correlation_id"] is None for payload in seen)

    async def test_stop_is_idempotent(self) -> None:
        sink = InMemorySseSink()
        emitter = SyntheticAgentActivityEmitter(sink=sink, channel="c")
        await emitter.stop()  # never started - must not raise
        await emitter.start()
        await emitter.stop()
        await emitter.stop()  # double stop - must not raise
