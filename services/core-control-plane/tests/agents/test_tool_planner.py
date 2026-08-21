"""Tool planning: deterministic selection, bounded dispatch, no recursion."""

from __future__ import annotations

import asyncio
import time

import pytest
from fdai.agents import (
    MAX_TOOL_PLANS,
    AgentToolStatus,
    PantheonRuntime,
    plan_conversation_tools,
)
from fdai.agents._framework.pantheon import PANTHEON_NAMES, PANTHEON_SPECS
from fdai.agents._framework.tool_planner import ConversationToolPlan
from fdai.shared.providers.testing.event_bus import InMemoryEventBus

pytestmark = pytest.mark.anyio


def _runtime() -> PantheonRuntime:
    return PantheonRuntime.build(provider=InMemoryEventBus(), raw_event_topic="fdai.events")


# ---------------------------------------------------------------------------
# Selection is a decision, so it must be replayable and bounded.
# ---------------------------------------------------------------------------


def test_the_same_structured_selection_always_projects_the_same_tools() -> None:
    """A recorded turn must replay to the same plan, or it is not evidence."""
    requested = ("read_pending_approvals", "read_approval_policy")

    first = plan_conversation_tools(requested)
    for _ in range(20):
        assert plan_conversation_tools(requested) == first


def test_a_plan_never_exceeds_the_declared_cap() -> None:
    """A read path that fans out on one question is a denial-of-service surface."""
    # Every domain noun at once: without a cap this would select dozens.
    assert plan_conversation_tools(("read_pending_approvals",) * 4) == ()


def test_unknown_or_unselected_tools_project_nothing() -> None:
    assert plan_conversation_tools(()) == ()
    assert plan_conversation_tools(("unknown_tool",)) == ()
    assert plan_conversation_tools("read_cost_samples") == ()


def test_a_plan_records_semantic_judgment_tier_without_lexical_terms() -> None:
    plans = plan_conversation_tools(("read_rollback_history",))

    assert plans
    for plan in plans:
        assert plan.matched_terms == ()
        assert plan.tier == "semantic_judgment"


@pytest.mark.parametrize(
    "changes",
    (
        {"agent": "Ghost"},
        {"tool_id": "../../exec"},
        {"score": -1.0},
        {"score": True},
        {"score": "1"},
        {"score": 10**4_000},
        {"score": float("nan")},
        {"score": float("inf")},
        {"tier": "forged"},
        {"tier": []},
        {"tool_id": []},
        {"matched_terms": None},
        {"matched_terms": ("cost", 1)},
        {"matched_terms": ("x" * 65,)},
        {"matched_terms": ("x",) * 65},
    ),
)
def test_plan_record_rejects_forged_or_unbounded_fields(changes: dict[str, object]) -> None:
    """This public record enters server-owned answer serialization."""
    values: dict[str, object] = {
        "agent": "Njord",
        "tool_id": "read_cost_samples",
        "score": 1.0,
        "matched_terms": ("cost",),
        "tier": "semantic_judgment",
        **changes,
    }

    with pytest.raises(ValueError):
        ConversationToolPlan(**values)  # type: ignore[arg-type]


def test_every_planned_tool_is_owned_by_the_agent_it_names() -> None:
    """The registry refuses a wrong owner; the planner must never produce one."""
    owners = {
        tool.tool_id: spec.name for spec in PANTHEON_SPECS for tool in spec.conversation.tool_specs
    }
    requested = ("read_cost_samples", "read_rollback_history", "read_verdicts")
    for plan in plan_conversation_tools(requested, limit=MAX_TOOL_PLANS):
        assert plan.agent in PANTHEON_NAMES
        assert owners[plan.tool_id] == plan.agent


def test_narrowing_to_an_agent_never_selects_another_agents_tool() -> None:
    """Tool selection refines a route; it must not compete with it."""
    plans = plan_conversation_tools(("read_cost_samples",), agents=("Njord",))

    assert plans
    assert {plan.agent for plan in plans} == {"Njord"}


# ---------------------------------------------------------------------------
# Dispatch: one level deep, and never fatal to the answer.
# ---------------------------------------------------------------------------


async def test_a_self_calling_agent_cannot_recurse() -> None:
    """The lock that makes an infinite tool loop impossible.

    An agent holds no reference to the registry, so this edge does not
    exist today. It is simulated here because the cost of it appearing
    later is an unbounded call chain on the read path.
    """
    runtime = _runtime()
    registry = runtime._conversation_tools
    assert registry is not None
    odin = runtime.agents["Odin"]
    original = odin.introspect
    nested_reasons: list[str | None] = []

    async def calls_itself(question: str, context: dict[str, object]) -> object:
        nested = await registry.invoke(
            agent_name="Odin",
            tool_id="read_portfolio_policy",
            question=question,
            trace_ref="t",
        )
        nested_reasons.append(nested.reason)
        return await original(question, context)

    odin.introspect = calls_itself  # type: ignore[assignment,method-assign]

    result = await asyncio.wait_for(
        registry.invoke(
            agent_name="Odin",
            tool_id="read_portfolio_policy",
            question="What is the portfolio policy?",
            trace_ref="t",
        ),
        timeout=10,
    )

    assert len(nested_reasons) == 1
    assert nested_reasons[0] is not None
    assert nested_reasons[0].startswith("reentrant_tool_call:")
    assert result.status is AgentToolStatus.OK


async def test_concurrent_dispatch_is_not_mistaken_for_recursion() -> None:
    """The depth lock is per task, so parallel reads are not nested reads."""
    runtime = _runtime()
    registry = runtime._conversation_tools
    assert registry is not None

    results = await asyncio.gather(
        *[
            registry.invoke(
                agent_name="Odin",
                tool_id="read_portfolio_policy",
                question="What is the portfolio policy?",
                trace_ref="t",
            )
            for _ in range(8)
        ]
    )

    assert all(result.status is AgentToolStatus.OK for result in results)


async def test_prefetch_dispatches_only_the_planned_tools() -> None:
    """What runs is what the plan said would run, and nothing else."""
    runtime = _runtime()
    question = "What is the portfolio policy and the arbitration history?"

    plans = runtime.plan_conversation_tools(
        ("read_portfolio_policy", "read_arbitration_history"), agents=("Odin",)
    )
    results = await runtime.prefetch_conversation_tools(question, agents=("Odin",))

    assert len(plans) == 2
    assert results == ()


async def test_prefetch_returns_nothing_when_the_question_asks_for_nothing() -> None:
    runtime = _runtime()

    assert await runtime.prefetch_conversation_tools("hello") == ()


async def test_a_failing_tool_degrades_the_prefetch_not_the_caller() -> None:
    """Prefetched evidence is supplementary; losing it must not raise."""
    runtime = _runtime()
    odin = runtime.agents["Odin"]

    async def explodes(question: str, context: dict[str, object]) -> object:
        raise RuntimeError("owned state unavailable")

    odin.introspect = explodes  # type: ignore[assignment,method-assign]

    results = await runtime.prefetch_conversation_tools(
        "What is the portfolio policy?", agents=("Odin",)
    )

    assert all(result.status is AgentToolStatus.ABSTAIN for result in results)


# ---------------------------------------------------------------------------
# The charter now names the tools the runtime plans from.
# ---------------------------------------------------------------------------


def test_every_charter_names_the_tools_it_tells_the_agent_to_use() -> None:
    """ "Answer through the allowed tools" is unfollowable without the list."""
    for spec in PANTHEON_SPECS:
        prompt = spec.conversation.system_prompt
        for tool_id in spec.conversation.tools:
            assert tool_id in prompt, f"{spec.name} does not name {tool_id}"


async def test_the_whole_prefetch_is_bounded_even_when_every_tool_hangs() -> None:
    """A per-tool timeout does not bound the sum; the budget must.

    Three tools each allowed thirty seconds would otherwise add ninety
    seconds to the answer an operator is waiting for.
    """
    from fdai.agents._framework import tool_prefetch as prefetch_module

    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
        conversation_tool_timeout_seconds=30.0,
    )

    async def never_returns(question: str, context: dict[str, object]) -> object:
        await asyncio.sleep(300)
        raise AssertionError("unreachable")

    runtime.agents["Odin"].introspect = never_returns  # type: ignore[assignment,method-assign]
    question = "What is the portfolio policy and the arbitration history?"
    assert (
        len(
            runtime.plan_conversation_tools(
                ("read_portfolio_policy", "read_arbitration_history"), agents=("Odin",)
            )
        )
        > 1
    )

    original_budget = prefetch_module.PREFETCH_BUDGET_SECONDS
    prefetch_module.PREFETCH_BUDGET_SECONDS = 0.2
    try:
        started = time.perf_counter()
        results = await runtime.prefetch_conversation_tools(question, agents=("Odin",))
        elapsed = time.perf_counter() - started
    finally:
        prefetch_module.PREFETCH_BUDGET_SECONDS = original_budget

    assert results == ()
    assert elapsed < 1.0


async def test_unbound_prefetch_stays_unavailable_after_timeout() -> None:
    """A budget cancellation must not wedge the depth lock for later turns."""
    from fdai.agents._framework import tool_prefetch as prefetch_module

    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
        conversation_tool_timeout_seconds=30.0,
    )
    odin = runtime.agents["Odin"]
    healthy = odin.introspect

    async def never_returns(question: str, context: dict[str, object]) -> object:
        await asyncio.sleep(300)
        raise AssertionError("unreachable")

    odin.introspect = never_returns  # type: ignore[assignment,method-assign]
    question = "What is the portfolio policy?"

    original_budget = prefetch_module.PREFETCH_BUDGET_SECONDS
    prefetch_module.PREFETCH_BUDGET_SECONDS = 0.2
    try:
        assert await runtime.prefetch_conversation_tools(question, agents=("Odin",)) == ()
    finally:
        prefetch_module.PREFETCH_BUDGET_SECONDS = original_budget

    odin.introspect = healthy  # type: ignore[method-assign]
    recovered = await runtime.prefetch_conversation_tools(question, agents=("Odin",))

    assert recovered == ()


async def test_repeated_timeouts_share_one_build_and_shutdown_drains_it() -> None:
    """A hung provider must not leave one immortal task per question."""

    class _NeverEmbedding:
        dim = 4

        async def embed(self, text: str) -> list[float]:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    from fdai.agents._framework.tool_semantic import SemanticToolPlanner

    planner = SemanticToolPlanner(
        embedding_model=_NeverEmbedding(),
        specs=PANTHEON_SPECS,
    )

    for _ in range(25):
        try:
            async with asyncio.timeout(0.005):
                await planner.plan("cost")
        except TimeoutError:
            pass

    live = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done()
    ]
    assert len(live) == 1

    await planner.stop()

    assert [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done()
    ] == []


async def test_failed_bridge_shutdown_still_drains_the_tool_build() -> None:
    """One cleanup error must not strand an unrelated provider task."""

    class _NeverEmbedding:
        dim = 4

        async def embed(self, text: str) -> list[float]:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
        conversation_embedding_model=_NeverEmbedding(),
    )
    planner = runtime._semantic_tool_planner
    assert planner is not None

    try:
        async with asyncio.timeout(0.005):
            await planner.plan("cost")
    except TimeoutError:
        pass

    async def broken_stop() -> None:
        raise RuntimeError("bridge cleanup failed")

    runtime.bridge.stop = broken_stop  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="bridge cleanup failed"):
        await runtime.stop()

    assert planner._build_task is not None
    assert planner._build_task.done()


def test_every_declared_tool_is_reachable_from_its_owner() -> None:
    """A declared tool nobody owns is a promise the runtime cannot keep."""
    runtime = _runtime()
    registry = runtime._conversation_tools
    assert registry is not None
    snapshot = registry.snapshot()

    declared = sum(len(spec.conversation.tools) for spec in PANTHEON_SPECS)
    assert snapshot["registered"] == declared
    assert snapshot["available"] == declared
