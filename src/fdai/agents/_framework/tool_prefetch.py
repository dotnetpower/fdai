"""Plan and run the read tools a question asks for, under one budget.

Split out of ``runtime.py`` so the runtime keeps its wiring role and this
keeps the dispatch policy: which tier chooses, how many tools may run,
and how long the whole gather may take. The runtime holds the seams; this
decides what to do with them.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fdai.agents._framework.tool_planner import (
    MAX_PLANNED_QUESTION_CHARS,
    PREFETCH_BUDGET_SECONDS,
    ConversationToolPlan,
    plan_conversation_tools,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fdai.agents._framework.conversation_tools import (
        AgentConversationToolRegistry,
        AgentToolResult,
    )
    from fdai.agents._framework.tool_semantic import SemanticToolPlanner

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ToolGatherResult:
    """One bounded plan and the results that completed under its deadline."""

    plans: tuple[ConversationToolPlan, ...]
    results: tuple[AgentToolResult, ...]
    timed_out: bool
    ambiguous: bool = False


async def plan_tools(
    question: str,
    *,
    semantic: SemanticToolPlanner | None,
    agents: Sequence[str],
    limit: int,
) -> tuple[ConversationToolPlan, ...]:
    """Choose by meaning when that is possible, lexically otherwise.

    Measured, not assumed. Against fourteen questions written the way
    operators actually ask them, lexical matching selected the right tool
    3 times, meaning selected it 13 times, and letting lexical decide
    first - the obvious cheap-tier-first arrangement - selected it 11.
    Lexical is not merely weaker; it is confidently wrong often enough to
    veto a better answer, because its score counts term overlap and two
    matched words say nothing about whether they were the right two.

    So meaning leads where it exists, and lexical is what the path
    degrades to: an unbound embedding, a provider failure, or a match
    below the confidence floor all fall back to it. A deployment with no
    embedding model therefore keeps exactly the behaviour it had, and one
    with an embedding never has a weak word match block a strong one.
    """
    if len(question) > MAX_PLANNED_QUESTION_CHARS:
        # Match the registry's boundary before spending an embedding or
        # producing a plan the registry can only refuse.
        return ()
    if semantic is not None:
        semantic_plans = await semantic.plan(question, agents=agents, limit=limit)
        if semantic_plans:
            return semantic_plans
    return plan_conversation_tools(question, agents=agents, limit=limit)


async def prefetch_tools(
    question: str,
    *,
    registry: AgentConversationToolRegistry,
    semantic: SemanticToolPlanner | None,
    agents: Sequence[str],
    limit: int,
    trace_ref: str,
) -> tuple[AgentToolResult, ...]:
    """Run the planned tools and return what completed.

    A hard bound across the whole gather, not one per tool. The registry
    bounds a single dispatch; without a budget over the sum, three tools
    each allowed to hang would add three timeouts to the answer an
    operator is waiting for. A deadline that only refused to *start* the
    next tool would still overrun by one full dispatch, so this cancels
    instead and returns what finished: partial supplementary evidence
    beats a slow answer, and no evidence beats a stalled one.
    """
    gathered = await gather_tools(
        question,
        registry=registry,
        semantic=semantic,
        agents=agents,
        limit=limit,
        trace_ref=trace_ref,
    )
    return gathered.results


async def gather_tools(
    question: str,
    *,
    registry: AgentConversationToolRegistry,
    semantic: SemanticToolPlanner | None,
    agents: Sequence[str],
    limit: int,
    trace_ref: str,
    execute_limit: int | None = None,
    require_unique_top: bool = False,
) -> ToolGatherResult:
    """Plan and execute owner tools while preserving timeout completeness."""

    plans: tuple[ConversationToolPlan, ...] = ()
    results: list[AgentToolResult] = []
    try:
        async with asyncio.timeout(PREFETCH_BUDGET_SECONDS):
            plans = await plan_tools(question, semantic=semantic, agents=agents, limit=limit)
            if require_unique_top and len(plans) > 1 and plans[0].score == plans[1].score:
                return ToolGatherResult(
                    plans=plans,
                    results=(),
                    timed_out=False,
                    ambiguous=True,
                )
            selected = plans[:execute_limit] if execute_limit is not None else plans
            for plan in selected:
                results.append(
                    await registry.invoke(
                        agent_name=plan.agent,
                        tool_id=plan.tool_id,
                        question=question,
                        trace_ref=trace_ref,
                    )
                )
    except TimeoutError:
        _LOG.warning(
            "pantheon_tool_prefetch_budget_exhausted",
            extra={"completed": len(results), "planned": len(plans)},
        )
        return ToolGatherResult(plans=plans, results=tuple(results), timed_out=True)
    return ToolGatherResult(plans=plans, results=tuple(results), timed_out=False)


__all__ = ["ToolGatherResult", "gather_tools", "plan_tools", "prefetch_tools"]
