"""Pantheon-backed Command Deck delegation tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fdai.agents import PantheonRuntime
from fdai.delivery.read_api.routes.chat_agent_delegate import PantheonChatDelegate
from fdai.delivery.read_api.routes.chat_evidence_enrichment import _with_agent_evidence
from fdai.shared.providers.testing.event_bus import InMemoryEventBus


def _delegate() -> PantheonChatDelegate:
    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
    )
    return PantheonChatDelegate(runtime)


def test_routes_question_to_owning_agent() -> None:
    result = asyncio.run(
        _delegate().delegate(
            prompt="cost breakdown",
            user_id="operator-1",
            session_id="conversation-1",
        )
    )

    assert result is not None
    assert result["primary_agent"] == "Njord"
    assert result["facts"]["agent"] == "Njord"


def test_same_client_session_is_isolated_between_users() -> None:
    delegate = _delegate()

    first = asyncio.run(
        delegate.delegate(
            prompt="cost breakdown",
            user_id="operator-1",
            session_id="shared",
        )
    )
    second = asyncio.run(
        delegate.delegate(
            prompt="cost breakdown",
            user_id="operator-2",
            session_id="shared",
        )
    )

    assert first is not None
    assert second is not None


def test_action_and_no_route_return_no_agent_evidence() -> None:
    delegate = _delegate()

    action = asyncio.run(
        delegate.delegate(
            prompt="restart svc-1",
            user_id="operator-1",
            session_id="conversation-1",
        )
    )
    unknown = asyncio.run(
        delegate.delegate(
            prompt="zzzz qqqq wxyz",
            user_id="operator-1",
            session_id="conversation-1",
        )
    )

    assert action is None
    assert unknown is None


def test_delegate_does_not_materialize_principal_scoped_chat_as_global_activity() -> None:
    delegate = _delegate()
    ask = AsyncMock(return_value=None)

    with patch.object(delegate.runtime, "ask", ask):
        result = asyncio.run(
            delegate.delegate(
                prompt="cost breakdown",
                user_id="operator-1",
                session_id="conversation-1",
            )
        )

    assert result is None
    call = ask.await_args.kwargs
    assert call["session_id"].startswith("web-")
    assert call["user_id"] == "operator-1"
    assert call["question"] == "cost breakdown"
    assert call["allow_action_proposal"] is False
    assert call["materialize_handoff"] is False


def test_specialist_abstention_becomes_an_explicit_handoff_to_bragi() -> None:
    delegate = _delegate()
    ask = AsyncMock(
        return_value=SimpleNamespace(
            answer={
                "answer": None,
                "primary_agent": "Heimdall",
                "abstain_reason": "insufficient_agent_evidence",
                "trace_ref": "trace-handoff",
            }
        )
    )

    with patch.object(delegate.runtime, "ask", ask):
        result = asyncio.run(
            delegate.delegate(
                prompt="@Heimdall explain the missing observation",
                user_id="operator-1",
                session_id="conversation-1",
            )
        )

    assert result == {
        "primary_agent": "Bragi",
        "answer": None,
        "facts": {},
        "contributors": [],
        "contributor_answers": [],
        "trace_ref": "trace-handoff",
        "handoff_from": "Heimdall",
        "handoff_reason": "insufficient_agent_evidence",
    }


def test_screen_data_questions_stay_with_bragi_t0() -> None:
    delegate = _delegate()
    context = {
        "routeId": "live",
        "facts": [
            {"key": "attention.total", "value": 3},
            {"key": "tier.t2", "value": "5%"},
        ],
    }

    assert delegate.should_delegate("몇 개가 주의가 필요해?", context) is False
    assert delegate.should_delegate("what is the T2 tier share?", context) is False
    assert delegate.should_delegate("그럼 T2는?", context) is False
    assert delegate.should_delegate("who logged the latest audit entry?", context) is False
    assert delegate.should_delegate("가장 흔한 액션이 뭐야?", context) is False
    assert delegate.should_delegate("which ActionType is ready to promote?", context) is False
    assert delegate.should_delegate("이 리소스 월 비용이 얼마야?", context) is False
    assert delegate.should_delegate("which Azure region is this deployed in?", context) is False
    assert delegate.should_delegate("cost breakdown", context) is True


def test_shadow_planning_route_is_deterministic_and_excludes_norns_and_odin() -> None:
    route = _delegate().route_answer_planning("Ask Freyr and Njord about capacity and cost")

    assert route.primary_agent == "Freyr"
    assert [candidate.agent for candidate in route.candidates] == ["Freyr", "Njord"]
    assert all(candidate.agent not in {"Norns", "Odin"} for candidate in route.candidates)


def test_collects_typed_agent_owned_contribution_without_tool_call() -> None:
    contribution = asyncio.run(
        _delegate().contribute(
            agent="Njord",
            prompt="Compare capacity and cost",
            max_tokens=400,
        )
    )

    assert contribution is not None
    assert contribution.agent == "Njord"
    assert contribution.facts
    assert all(fact.evidence_ref.startswith("agent-owned:njord:") for fact in contribution.facts)
    assert set(fact.evidence_ref for fact in contribution.facts) <= set(contribution.evidence_refs)


def test_shadow_contributor_refuses_action_and_synchronous_norns() -> None:
    delegate = _delegate()

    action = asyncio.run(delegate.contribute(agent="Thor", prompt="restart svc-1", max_tokens=400))
    learner = asyncio.run(
        delegate.contribute(agent="Norns", prompt="Why did this fail?", max_tokens=400)
    )

    assert action is None
    assert learner is None


async def test_selected_agent_binding_persists_until_operator_explicitly_overrides_it() -> None:
    prompts: list[str] = []

    class _CapturingDelegate:
        async def delegate(
            self,
            *,
            prompt: str,
            user_id: str,
            session_id: str,
        ) -> dict[str, object]:
            del user_id, session_id
            prompts.append(prompt)
            return {
                "primary_agent": "Heimdall",
                "answer": "No active work.",
                "facts": {},
            }

    delegate = _CapturingDelegate()
    context = {
        "kind": "incident",
        "incident_id": "INC-example",
        "correlation_id": "corr-example",
        "selected_agent": "Heimdall",
    }

    await _with_agent_evidence(
        "What have you been working on?",
        {},
        delegate,
        user_id="operator-1",
        session_id="conversation-1",
        conversation_context=context,
    )
    await _with_agent_evidence(
        "@Forseti verify this decision",
        {},
        delegate,
        user_id="operator-1",
        session_id="conversation-1",
        conversation_context=context,
    )

    assert prompts == [
        "@Heimdall What have you been working on?",
        "@Forseti verify this decision",
    ]
