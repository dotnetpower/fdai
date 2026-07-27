"""Pantheon-backed Command Deck delegation tests."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fdai.agents import PANTHEON_SPECS, PantheonRuntime
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
    njord = next(spec for spec in PANTHEON_SPECS if spec.name == "Njord")
    assert result["conversation_policy"] == njord.conversation_policy()


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
        # Prefetched before the turn, so a handoff still carries whatever
        # scoped evidence the question asked for.
        "tool_evidence": [],
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
    await _with_agent_evidence(
        "Compare Thor with the current observer",
        {},
        delegate,
        user_id="operator-1",
        session_id="conversation-1",
        conversation_context=context,
    )

    assert prompts == [
        "@Heimdall What have you been working on?",
        "@Forseti verify this decision",
        "@Heimdall Compare Thor with the current observer",
    ]


async def test_evidence_from_another_owner_never_rides_on_this_answer() -> None:
    """The plan runs before the turn, so routing and the turn can disagree.

    When they do, the prefetched reads belong to an agent that did not
    answer. Presenting them beside this answer would offer a read that
    had nothing to do with it as if it were its grounding.
    """
    from fdai.agents import AgentToolStatus

    class _MismatchedRuntime:
        async def route_conversation_owner(self, prompt: str) -> str | None:
            return "Njord"

        async def prefetch_conversation_tools(
            self, prompt: str, *, agents: tuple[str, ...] = (), **kwargs: object
        ) -> tuple[object, ...]:
            return (
                SimpleNamespace(
                    agent=agents[0] if agents else "?",
                    tool_id="read_cost_samples",
                    answer="observed cost samples",
                    facts={"tracked_scopes_count": 2},
                    evidence_refs=("agent:Njord/state",),
                    status=AgentToolStatus.OK,
                ),
            )

        async def ask(self, **kwargs: object) -> object:
            return SimpleNamespace(
                answer={
                    "answer": "Capacity holds for now.",
                    "primary_agent": "Freyr",
                    "facts": {},
                    "trace_ref": "trace-1",
                }
            )

    delegate = PantheonChatDelegate(runtime=_MismatchedRuntime())  # type: ignore[arg-type]

    result = await delegate.delegate(prompt="용량 늘려야 하나", user_id="u", session_id="s")

    assert result is not None
    assert result["primary_agent"] == "Freyr"
    assert result["tool_evidence"] == []


async def test_a_question_nobody_owns_spends_no_reads() -> None:
    """A ranker always ranks, so ownership must be decided elsewhere.

    Similarity alone cannot tell "why did the bill go up" from "tell me
    a joke": the nearest tool to an unrelated question still scores like
    a match, and the tier would dispatch three reads and attach evidence
    for a question the system owns nothing about. The route decides
    ownership against a tuned floor; no owner means no prefetch.
    """
    dispatched: list[str] = []

    class _UnownedRuntime:
        async def route_conversation_owner(self, prompt: str) -> str | None:
            return None

        async def prefetch_conversation_tools(
            self, prompt: str, **kwargs: object
        ) -> tuple[object, ...]:
            dispatched.append(prompt)  # pragma: no cover - must not happen
            return ()

        async def ask(self, **kwargs: object) -> object:
            return SimpleNamespace(
                answer={
                    "answer": "I can help with operations questions.",
                    "primary_agent": "Bragi",
                    "facts": {},
                    "trace_ref": "trace-1",
                }
            )

    delegate = PantheonChatDelegate(runtime=_UnownedRuntime())  # type: ignore[arg-type]

    result = await delegate.delegate(prompt="tell me a joke", user_id="u", session_id="s")

    assert result is not None
    assert result["tool_evidence"] == []
    assert dispatched == []


async def test_the_owner_that_answers_is_the_owner_that_was_read() -> None:
    """Keywords settle few real questions, so the route must be the full one."""
    asked: list[tuple[str, ...]] = []

    class _OwnedRuntime:
        async def route_conversation_owner(self, prompt: str) -> str | None:
            return "Njord"

        async def prefetch_conversation_tools(
            self, prompt: str, *, agents: tuple[str, ...] = (), **kwargs: object
        ) -> tuple[object, ...]:
            asked.append(agents)
            return ()

        async def ask(self, **kwargs: object) -> object:
            return SimpleNamespace(
                answer={
                    "answer": "Spend is within budget.",
                    "primary_agent": "Njord",
                    "facts": {},
                    "trace_ref": "trace-1",
                }
            )

    delegate = PantheonChatDelegate(runtime=_OwnedRuntime())  # type: ignore[arg-type]

    await delegate.delegate(prompt="why did we get billed so much", user_id="u", session_id="s")

    assert asked == [("Njord",)]


async def test_a_stalled_route_costs_the_evidence_not_the_answer() -> None:
    """The route runs before the turn, so an unbounded one holds the answer.

    Prefetch was already bounded, but the gate that decides whether to
    prefetch was not, and it is awaited first. An embedding provider that
    stops responding would have stalled the operator's reply rather than
    just the evidence beside it.
    """
    from fdai.delivery.read_api.routes import chat_agent_delegate as delegate_module

    class _StalledRuntime:
        async def route_conversation_owner(self, prompt: str) -> str | None:
            await asyncio.sleep(300)
            raise AssertionError("unreachable")

        async def prefetch_conversation_tools(
            self, prompt: str, **kwargs: object
        ) -> tuple[object, ...]:
            raise AssertionError("must not dispatch without an owner")

        async def ask(self, **kwargs: object) -> object:
            return SimpleNamespace(
                answer={
                    "answer": "Spend is within budget.",
                    "primary_agent": "Njord",
                    "facts": {},
                    "trace_ref": "trace-1",
                }
            )

    original = delegate_module.ROUTE_BUDGET_SECONDS
    delegate_module.ROUTE_BUDGET_SECONDS = 0.05
    try:
        delegate = PantheonChatDelegate(runtime=_StalledRuntime())  # type: ignore[arg-type]
        started = time.perf_counter()
        result = await delegate.delegate(
            prompt="우리 돈 얼마나 쓰고 있어?", user_id="u", session_id="s"
        )
        elapsed = time.perf_counter() - started
    finally:
        delegate_module.ROUTE_BUDGET_SECONDS = original

    assert result is not None
    assert result["answer"] == "Spend is within budget."
    assert result["tool_evidence"] == []
    assert elapsed < 1.0


async def test_a_broken_route_provider_costs_the_evidence_not_the_answer() -> None:
    class _BrokenRouteRuntime:
        async def route_conversation_owner(self, prompt: str) -> str | None:
            raise RuntimeError("embedding provider down")

        async def prefetch_conversation_tools(
            self, prompt: str, **kwargs: object
        ) -> tuple[object, ...]:
            raise AssertionError("must not dispatch without an owner")

        async def ask(self, **kwargs: object) -> object:
            return SimpleNamespace(
                answer={
                    "answer": "Spend is within budget.",
                    "primary_agent": "Njord",
                    "facts": {},
                    "trace_ref": "trace-1",
                }
            )

    delegate = PantheonChatDelegate(runtime=_BrokenRouteRuntime())  # type: ignore[arg-type]

    result = await delegate.delegate(prompt="비용", user_id="u", session_id="s")

    assert result is not None
    assert result["answer"] == "Spend is within budget."
    assert result["tool_evidence"] == []
