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
    ConversationToolPlan,
)
from fdai.agents._framework.tool_planner import (
    PREFETCH_BUDGET_SECONDS as DEFAULT_PREFETCH_BUDGET_SECONDS,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fdai.agents._framework.conversation_tools import (
        AgentConversationToolRegistry,
        AgentToolResult,
    )
    from fdai.agents._framework.tool_semantic import SemanticToolPlanner

_LOG = logging.getLogger(__name__)

# Runtime copy of the canonical default. Tests and a composition root may
# tune the gather deadline without mutating a ``Final`` source constant.
PREFETCH_BUDGET_SECONDS: float = DEFAULT_PREFETCH_BUDGET_SECONDS


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
    """Choose by model-backed meaning or return an explicit empty plan."""
    if len(question) > MAX_PLANNED_QUESTION_CHARS:
        # Match the registry's boundary before spending an embedding or
        # producing a plan the registry can only refuse.
        return ()
    if semantic is not None:
        return await semantic.plan(question, agents=agents, limit=limit)
    return ()


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


__all__ = [
    "PREFETCH_BUDGET_SECONDS",
    "ToolGatherResult",
    "gather_tools",
    "plan_tools",
    "prefetch_tools",
]
