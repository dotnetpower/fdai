"""Conversational-port wiring: PantheonRuntime.ask routes through Bragi."""

from __future__ import annotations

import asyncio

import pytest

from fdai.agents._framework.runtime import PantheonRuntime
from fdai.shared.providers.testing.event_bus import InMemoryEventBus

_RAW_TOPIC = "fdai.events"


def _runtime(**kwargs: object) -> PantheonRuntime:
    return PantheonRuntime.build(provider=InMemoryEventBus(), raw_event_topic=_RAW_TOPIC, **kwargs)


def test_ask_routes_to_primary_agent() -> None:
    runtime = _runtime()
    turn = asyncio.run(
        runtime.ask(session_id="s1", user_id="u1", question="what is the action status")
    )
    assert turn is not None
    assert turn.primary_agent == "Thor"  # Thor owns question_domain 'action_status'
    assert turn.answer["primary_agent"] == "Thor"


def test_ask_tracks_session_turns() -> None:
    runtime = _runtime()
    asyncio.run(runtime.ask(session_id="s1", user_id="u1", question="action status"))
    turn2 = asyncio.run(runtime.ask(session_id="s1", user_id="u1", question="approval backlog"))
    assert turn2 is not None
    assert turn2.turn_index == 1


def test_ask_enforces_user_ownership() -> None:
    runtime = _runtime()
    asyncio.run(runtime.ask(session_id="s1", user_id="u1", question="action status"))
    with pytest.raises(PermissionError):
        asyncio.run(runtime.ask(session_id="s1", user_id="u2", question="action status"))


def test_conversational_port_present_in_health() -> None:
    runtime = _runtime()
    assert runtime.health()["conversational_port"] is True


def test_conversational_port_absent_when_bragi_disabled() -> None:
    runtime = _runtime(disabled_agents=frozenset({"Bragi"}))
    assert runtime.health()["conversational_port"] is False
    result = asyncio.run(runtime.ask(session_id="s", user_id="u", question="action status"))
    assert result is None


def test_ask_handoff_when_no_route() -> None:
    runtime = _runtime()
    turn = asyncio.run(runtime.ask(session_id="s1", user_id="u1", question="zzzz qqqq wxyz"))
    assert turn is not None
    assert turn.primary_agent is None
    assert turn.answer["handoff_needed"] is True


def test_ask_handoff_escalates_to_saga_issue_and_dedups() -> None:
    # An unanswerable question triggers the discovery-loop handoff: the runtime
    # asks Saga to open a fingerprinted issue (governance.escalate-to-github-issue).
    from fdai.agents.saga import Saga

    runtime = _runtime()
    saga = runtime.agents["Saga"]
    assert isinstance(saga, Saga)

    asyncio.run(runtime.ask(session_id="s1", user_id="u1", question="zzzz qqqq wxyz"))
    assert len(saga.github.issues) == 1

    # A repeated identical ask deduplicates by fingerprint (comment, not a new
    # issue) so recurring unanswerable questions do not spam.
    asyncio.run(runtime.ask(session_id="s1", user_id="u1", question="zzzz qqqq wxyz"))
    assert len(saga.github.issues) == 1
    fingerprint = next(iter(saga.github.issues))
    assert len(saga.github.issues[fingerprint].comments) == 1  # second ask commented

    # A resolved question (routes to Thor) does NOT escalate.
    asyncio.run(runtime.ask(session_id="s2", user_id="u2", question="what is the action status"))
    assert len(saga.github.issues) == 1


def test_ask_resolved_question_does_not_escalate() -> None:
    from fdai.agents.saga import Saga

    runtime = _runtime()
    saga = runtime.agents["Saga"]
    assert isinstance(saga, Saga)
    asyncio.run(runtime.ask(session_id="s1", user_id="u1", question="what is the action status"))
    assert saga.github.issues == {}


def test_ask_answers_from_owned_state_not_stub() -> None:
    # The routed agent answers from its owned data (grounded), not a bare
    # not-implemented abstain.
    runtime = _runtime()
    turn = asyncio.run(runtime.ask(session_id="s1", user_id="u1", question="cost breakdown"))
    assert turn is not None
    assert turn.primary_agent == "Njord"
    assert turn.answer["answer"] is not None
    assert turn.answer["abstain_reason"] is None
    assert turn.answer["facts"]["agent"] == "Njord"


def test_ask_refuses_action_intent_and_routes_to_typed_pipeline() -> None:
    # A command ("restart ...") is not answered or executed by the
    # conversational port; Bragi translates it into a typed ActionProposal and
    # submits it to the pipeline via Huginn (agent-pantheon.md 7.7). The full
    # pantheon here wires the proposal sink, so the request is SUBMITTED, not
    # merely signalled - and the port never executes it.
    runtime = _runtime()
    turn = asyncio.run(runtime.ask(session_id="s1", user_id="u1", question="restart svc-1 now"))
    assert turn is not None
    assert turn.answer["answer"] is None  # the port did not answer/execute
    assert turn.answer["requires_typed_pipeline"] is True
    assert turn.answer["submitted"] is True
    assert turn.answer["action_type"] == "ops.restart-service"
    assert turn.answer["correlation_id"].startswith("conv-")
    assert turn.answer["initiator_principal"] == "u1"


# ---------------------------------------------------------------------------
# Agent-to-agent (A2A) introspection (agent-pantheon.md 6.2)
# ---------------------------------------------------------------------------


def test_introspect_a2a_answers_from_target_agent() -> None:
    runtime = _runtime()
    result = asyncio.run(
        runtime.introspect("Njord", "what is the cost breakdown", requester="Forseti")
    )
    assert result is not None
    assert result["primary_agent"] == "Njord"
    assert result["answer"] is not None
    assert result["requester"] == "Forseti"


def test_introspect_a2a_threads_correlation_trace() -> None:
    runtime = _runtime()
    result = asyncio.run(
        runtime.introspect(
            "Saga",
            "who executed correlation c-1",
            requester="Odin",
            correlation_id="c-1",
        )
    )
    assert result is not None
    assert result["trace_ref"] == "c-1"
    assert result["requester"] == "Odin"


def test_introspect_a2a_refuses_action_intent() -> None:
    runtime = _runtime()
    result = asyncio.run(runtime.introspect("Thor", "restart vm-1", requester="Odin"))
    assert result is not None
    assert result["abstain_reason"] == "requires_typed_pipeline"
    assert result["requester"] == "Odin"


def test_introspect_a2a_unknown_agent_abstains() -> None:
    runtime = _runtime()
    result = asyncio.run(runtime.introspect("Bragi", "anything", requester="Odin"))
    # Bragi does not register itself as a responder.
    assert result is not None
    assert result["abstain_reason"] == "responder_not_registered"


def test_introspect_a2a_none_when_bragi_disabled() -> None:
    runtime = _runtime(disabled_agents=frozenset({"Bragi"}))
    result = asyncio.run(runtime.introspect("Njord", "cost", requester="Forseti"))
    assert result is None


def test_introspect_a2a_rejects_unknown_requester() -> None:
    # A2A is pantheon-internal; an unknown requester would poison the audit
    # trail, so it is rejected at the boundary (H3).
    runtime = _runtime()
    with pytest.raises(ValueError, match="unknown requester"):
        asyncio.run(runtime.introspect("Njord", "cost", requester="Sauron"))


def test_introspect_a2a_does_not_mutate_responder_dict() -> None:
    # Bragi must not mutate a dict a fork responder may still own (H4).
    from fdai.agents.bragi import Bragi

    bragi = Bragi()
    shared = {"answer": "cached"}

    async def responder(question: str, context: dict) -> dict:
        return shared

    bragi.register_responder("Njord", responder)
    out = asyncio.run(bragi.introspect_agent("Njord", "cost", requester="Forseti"))
    assert out["requester"] == "Forseti"
    assert "requester" not in shared
    assert "primary_agent" not in shared


def test_introspect_facts_lists_are_capped() -> None:
    # An agent listing owned identifiers bounds the list and reports the true
    # count separately (H5).
    from fdai.agents.njord import Njord

    njord = Njord()
    for i in range(30):
        asyncio.run(njord.ingest_cost_sample(scope=f"scope-{i:02d}", amount_usd=1.0))
    result = asyncio.run(njord.on_conversation_turn("cost overview", {}))
    assert len(result["facts"]["tracked_scopes"]) == 20
    assert result["facts"]["tracked_scopes_count"] == 30


def test_introspect_freyr_facts_lists_are_capped() -> None:
    # Freyr exposes tracked resource ids; the list is bounded with a true
    # count, consistent with the other domain agents (H5).
    from fdai.agents.freyr import Freyr

    freyr = Freyr()
    for i in range(30):
        asyncio.run(freyr.ingest_utilization(resource_id=f"res-{i:02d}", utilization=0.5))
    result = asyncio.run(freyr.on_conversation_turn("capacity overview", {}))
    assert len(result["facts"]["tracked_resources"]) == 20
    assert result["facts"]["tracked_resources_count"] == 30
