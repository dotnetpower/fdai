"""Tests for the real-path StageEvent -> agent-activity projection (Phase 4)."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.delivery.read_api.streaming.agent_activity_projection import (
    AgentActivityProjection,
    project_stage,
    stage_agent,
)
from fdai.delivery.read_api.streaming.agent_activity_stream import (
    AgentState,
    AgentStateEvent,
    ConversationTurnEvent,
    IncidentTicketEvent,
    TicketStatus,
    TurnKind,
)
from fdai.shared.providers.stage_publisher import StageEvent, StageName, StagePhase

_TS = datetime(2026, 7, 12, 9, 0, 0, tzinfo=UTC)


def _stage(
    stage: StageName,
    phase: StagePhase = StagePhase.BEGIN,
    *,
    correlation_id: str = "corr-1",
    event_id: str = "evt-1",
    detail: dict[str, object] | None = None,
    error: str | None = None,
) -> StageEvent:
    return StageEvent(
        event_id=event_id,
        correlation_id=correlation_id,
        stage=stage,
        phase=phase,
        ts=_TS,
        detail=detail or {},
        error=error,
    )


def _run(events: list[StageEvent]) -> tuple[AgentActivityProjection, list[object]]:
    projection = AgentActivityProjection()
    emitted: list[object] = []
    for e in events:
        result = project_stage(projection, e)
        projection = result.projection
        emitted.extend(result.events)
    return projection, emitted


class TestStageAgent:
    def test_maps_each_stage_to_its_owner(self) -> None:
        assert stage_agent(StageName.INGEST, {}) == "Huginn"
        assert stage_agent(StageName.ROUTE, {}) == "Heimdall"
        assert stage_agent(StageName.VERIFY, {}) == "Forseti"
        assert stage_agent(StageName.GATE, {}) == "Forseti"
        assert stage_agent(StageName.EXECUTE, {}) == "Thor"
        assert stage_agent(StageName.AUDIT, {}) == "Saga"

    def test_hil_gate_is_var_not_forseti(self) -> None:
        assert stage_agent(StageName.GATE, {"gate_decision": "hil"}) == "Var"

    def test_non_hil_gate_is_forseti(self) -> None:
        assert stage_agent(StageName.GATE, {"gate_decision": "auto"}) == "Forseti"


class TestAgentState:
    def test_ingest_begin_emits_huginn_collecting(self) -> None:
        _proj, events = _run([_stage(StageName.INGEST, StagePhase.BEGIN)])
        state_events = [e for e in events if isinstance(e, AgentStateEvent)]
        assert len(state_events) == 1
        assert state_events[0].agent == "Huginn"
        assert state_events[0].state is AgentState.COLLECTING
        assert state_events[0].correlation_id == "corr-1"

    def test_done_phase_still_shows_the_active_ring(self) -> None:
        # The real ControlLoop emits a stage as a single DONE frame, so DONE
        # must light the agent up with what it just did, not reset it to idle.
        _proj, events = _run(
            [
                _stage(StageName.INGEST, StagePhase.DONE),
            ]
        )
        state_events = [e for e in events if isinstance(e, AgentStateEvent)]
        assert state_events[-1].agent == "Huginn"
        assert state_events[-1].state is AgentState.COLLECTING

    def test_hil_gate_emits_var_approving(self) -> None:
        _proj, events = _run(
            [_stage(StageName.GATE, StagePhase.BEGIN, detail={"gate_decision": "hil"})]
        )
        state_events = [e for e in events if isinstance(e, AgentStateEvent)]
        assert state_events[0].agent == "Var"
        assert state_events[0].state is AgentState.APPROVING

    def test_failed_phase_carries_error_detail(self) -> None:
        _proj, events = _run([_stage(StageName.EXECUTE, StagePhase.FAILED, error="lock timeout")])
        state_events = [e for e in events if isinstance(e, AgentStateEvent)]
        assert state_events[0].state is AgentState.IDLE
        assert state_events[0].detail is not None
        assert "lock timeout" in state_events[0].detail


class TestIncidentTicket:
    def test_first_stage_opens_a_ticket(self) -> None:
        _proj, events = _run([_stage(StageName.INGEST, detail={"severity": "high"})])
        tickets = [e for e in events if isinstance(e, IncidentTicketEvent)]
        assert len(tickets) == 1
        assert tickets[0].status is TicketStatus.OPEN
        assert tickets[0].ticket_id == "INC-corr-1"
        assert tickets[0].severity == "high"
        assert "Huginn" in tickets[0].involved_agents

    def test_gate_advances_to_investigating(self) -> None:
        _proj, events = _run(
            [
                _stage(StageName.INGEST),
                _stage(StageName.GATE, detail={"gate_decision": "auto"}),
            ]
        )
        tickets = [e for e in events if isinstance(e, IncidentTicketEvent)]
        assert tickets[-1].status is TicketStatus.INVESTIGATING

    def test_audit_done_resolves(self) -> None:
        _proj, events = _run(
            [
                _stage(StageName.INGEST),
                _stage(StageName.GATE),
                _stage(
                    StageName.AUDIT,
                    StagePhase.DONE,
                    detail={"outcome": "executed", "decision": "auto"},
                ),
            ]
        )
        tickets = [e for e in events if isinstance(e, IncidentTicketEvent)]
        assert tickets[-1].status is TicketStatus.RESOLVED

    def test_audit_abstain_preserves_open_status(self) -> None:
        _proj, events = _run(
            [
                _stage(StageName.INGEST),
                _stage(
                    StageName.AUDIT,
                    StagePhase.DONE,
                    detail={"outcome": "abstained_routing", "decision": "abstain"},
                ),
            ]
        )
        tickets = [e for e in events if isinstance(e, IncidentTicketEvent)]
        assert tickets[-1].status is TicketStatus.OPEN

    def test_audit_hil_keeps_only_var_engaged(self) -> None:
        _proj, events = _run(
            [
                _stage(StageName.INGEST),
                _stage(
                    StageName.AUDIT,
                    StagePhase.DONE,
                    detail={"outcome": "hil", "decision": "hil"},
                ),
            ]
        )
        tickets = [e for e in events if isinstance(e, IncidentTicketEvent)]
        states = [e for e in events if isinstance(e, AgentStateEvent)]
        assert tickets[-1].status is TicketStatus.INVESTIGATING
        assert "Var" in tickets[-1].involved_agents
        assert states[-1].agent == "Var"
        assert states[-1].state is AgentState.APPROVING
        assert states[-1].correlation_id == "corr-1"

    def test_terminal_audit_resets_completed_agents_to_idle(self) -> None:
        _proj, events = _run(
            [
                _stage(StageName.INGEST),
                _stage(StageName.ROUTE),
                _stage(
                    StageName.AUDIT,
                    StagePhase.DONE,
                    detail={"outcome": "executed", "decision": "auto"},
                ),
            ]
        )
        states = [e for e in events if isinstance(e, AgentStateEvent)]
        terminal = states[-3:]
        assert {event.agent for event in terminal} == {"Huginn", "Heimdall", "Saga"}
        assert all(event.state is AgentState.IDLE for event in terminal)
        assert all(event.correlation_id is None for event in terminal)

    def test_resolved_is_terminal(self) -> None:
        proj, _ = _run(
            [
                _stage(StageName.INGEST),
                _stage(
                    StageName.AUDIT,
                    StagePhase.DONE,
                    detail={"outcome": "executed", "decision": "auto"},
                ),
            ]
        )
        # A late stray frame on a resolved incident does not un-resolve it.
        result = project_stage(proj, _stage(StageName.GATE))
        assert result.projection.incidents["corr-1"].status is TicketStatus.RESOLVED

    def test_involved_agents_accumulate_across_stages(self) -> None:
        proj, _ = _run(
            [
                _stage(StageName.INGEST),
                _stage(StageName.ROUTE),
                _stage(StageName.VERIFY),
                _stage(StageName.EXECUTE),
            ]
        )
        involved = proj.incidents["corr-1"].involved
        assert {"Huginn", "Heimdall", "Forseti", "Thor"} <= set(involved)

    def test_same_agent_twice_is_not_double_listed(self) -> None:
        # Forseti owns both verify and gate; the second sighting is idempotent.
        proj, _ = _run(
            [
                _stage(StageName.INGEST),
                _stage(StageName.VERIFY),
                _stage(StageName.GATE, detail={"gate_decision": "auto"}),
            ]
        )
        involved = proj.incidents["corr-1"].involved
        assert involved.count("Forseti") == 1

    def test_a_new_agent_rides_a_ticket_frame_so_the_console_lights_it_up(self) -> None:
        # The console only reads `involved` from ticket frames, so each newly
        # engaged agent MUST produce a ticket event.
        _proj, events = _run([_stage(StageName.INGEST), _stage(StageName.ROUTE)])
        tickets = [e for e in events if isinstance(e, IncidentTicketEvent)]
        assert len(tickets) >= 2
        assert "Heimdall" in tickets[-1].involved_agents

    def test_two_correlations_do_not_cross_talk(self) -> None:
        proj, _ = _run(
            [
                _stage(StageName.INGEST, correlation_id="corr-a"),
                _stage(StageName.INGEST, correlation_id="corr-b"),
            ]
        )
        assert set(proj.incidents) == {"corr-a", "corr-b"}
        assert proj.incidents["corr-a"].ticket_id == "INC-corr-a"

    def test_conversation_turns_are_only_grounded_handoffs(self) -> None:
        # A stage transition between two agents is a real handoff; the
        # projection emits conversation.turn frames of kind HANDOFF only,
        # never a fabricated question/answer dialogue.
        _proj, events = _run(
            [
                _stage(StageName.INGEST),
                _stage(StageName.ROUTE),
                _stage(StageName.GATE),
                _stage(StageName.EXECUTE),
                _stage(StageName.AUDIT, StagePhase.DONE),
            ]
        )
        turns = [e for e in events if isinstance(e, ConversationTurnEvent)]
        assert turns, "real stage transitions MUST surface as handoff turns"
        assert all(t.kind is TurnKind.HANDOFF for t in turns)


class TestHandoffTurns:
    def test_first_stage_emits_no_handoff(self) -> None:
        # Nothing precedes the first agent, so there is no handoff.
        _proj, events = _run([_stage(StageName.INGEST)])
        turns = [e for e in events if isinstance(e, ConversationTurnEvent)]
        assert turns == []

    def test_stage_transition_emits_a_handoff(self) -> None:
        _proj, events = _run([_stage(StageName.INGEST), _stage(StageName.ROUTE)])
        turns = [e for e in events if isinstance(e, ConversationTurnEvent)]
        assert len(turns) == 1
        assert turns[0].from_agent == "Huginn"
        assert turns[0].to_agent == "Heimdall"
        assert turns[0].kind is TurnKind.HANDOFF

    def test_hil_gate_handoff_escalates_to_var(self) -> None:
        _proj, events = _run(
            [
                _stage(StageName.INGEST),
                _stage(StageName.GATE, detail={"gate_decision": "hil"}),
            ]
        )
        turns = [e for e in events if isinstance(e, ConversationTurnEvent)]
        assert turns[-1].to_agent == "Var"
        assert turns[-1].text == "escalating for HIL approval"

    def test_same_agent_twice_emits_no_handoff(self) -> None:
        # Forseti owns verify and gate; no handoff between the two.
        _proj, events = _run(
            [
                _stage(StageName.VERIFY),
                _stage(StageName.GATE, detail={"gate_decision": "auto"}),
            ]
        )
        turns = [e for e in events if isinstance(e, ConversationTurnEvent)]
        assert turns == []

    def test_handoff_text_is_grounded_in_the_destination_stage(self) -> None:
        _proj, events = _run([_stage(StageName.INGEST), _stage(StageName.EXECUTE)])
        turns = [e for e in events if isinstance(e, ConversationTurnEvent)]
        assert turns[-1].text == "executing the approved action"


class TestDeterminism:
    def test_same_input_yields_identical_output(self) -> None:
        seq = [
            _stage(StageName.INGEST),
            _stage(StageName.GATE),
            _stage(StageName.AUDIT, StagePhase.DONE),
        ]
        _p1, e1 = _run(list(seq))
        _p2, e2 = _run(list(seq))
        assert e1 == e2


class TestDetailShaping:
    def test_ticket_title_uses_the_firing_rule_when_present(self) -> None:
        _proj, events = _run(
            [_stage(StageName.INGEST, detail={"rule": "storage.public-blob.deny"})]
        )
        tickets = [e for e in events if isinstance(e, IncidentTicketEvent)]
        assert tickets[0].title == "Rule storage.public-blob.deny"

    def test_agent_state_detail_carries_the_resolving_tier(self) -> None:
        _proj, events = _run([_stage(StageName.ROUTE, detail={"tier": "t0"})])
        state_events = [e for e in events if isinstance(e, AgentStateEvent)]
        assert state_events[0].detail == "route (t0)"
