"""Validate model-selected owned read tools before any agent runs.

A charter tells its agent to "answer only from owned state through the
allowed tools", but nothing in the read path ever dispatched one, so the
instruction described a surface no turn could reach. This module closes
that gap from the outside: it picks the tools a question calls for, so a
caller can gather scoped evidence *before* the answering turn instead of
asking an agent to narrate what it might have looked at.

Natural-language selection belongs to a model-backed semantic boundary.
This module only projects exact canonical tool ids and verifies ownership.

Dispatch stays one level deep. Planning happens outside the agent, and an
agent holds no reference to the tool registry, so there is no edge from a
turn back into a tool. :mod:`fdai.agents._framework.conversation_tools`
refuses a nested call as the second lock.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from fdai.agents._framework.pantheon import PANTHEON_SPECS

#: Tools one question may dispatch. A question that appears to want more
#: than a handful of reads is a question that wants a report, and a read
#: path that fans out without a cap is a denial-of-service surface.
MAX_TOOL_PLANS: Final[int] = 3

#: Wall-clock seconds one question may spend gathering prefetched
#: evidence, across every tool it planned. A tool's own timeout bounds
#: one dispatch; this bounds the sum, so a question cannot add several
#: timeouts to the answer an operator is waiting for.
PREFETCH_BUDGET_SECONDS: Final[float] = 5.0

#: Question characters the planner reads. Matches the tool registry's own
#: question ceiling so a question it would refuse cannot be planned for.
MAX_PLANNED_QUESTION_CHARS: Final[int] = 2_000

_PLAN_TIERS: Final[frozenset[str]] = frozenset({"semantic_judgment", "t1_semantic"})
_PLAN_OWNERS: Final[dict[str, str]] = {
    tool.tool_id: spec.name for spec in PANTHEON_SPECS for tool in spec.conversation.tool_specs
}
_MAX_PLAN_TERM_CHARS: Final[int] = 64
_MAX_MATCHED_TERMS: Final[int] = 64


def _is_finite_score(value: object) -> bool:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True, slots=True)
class ConversationToolPlan:
    """One tool the question asks for, and why it was selected.

    ``matched_terms`` is the evidence for the selection itself. A plan
    that cannot say which words chose it is a guess, and a guess is not
    something a read path should act on unattended.
    """

    agent: str
    tool_id: str
    score: float
    """How well this tool matched, in the selecting tier's own units.

    Lexical counts matched terms; semantic scales a cosine. The two are
    NOT comparable, which is why ``tier`` is a field rather than
    something a reader has to infer from the number. Semantic scores
    keep their fractional precision because rounding two distinct
    matches into the same integer would create a false ambiguity.
    """

    matched_terms: tuple[str, ...]
    tier: str = "semantic_judgment"

    def __post_init__(self) -> None:
        if not isinstance(self.agent, str) or not isinstance(self.tool_id, str):
            raise ValueError("conversation tool plan owner and tool id MUST be strings")
        owner = _PLAN_OWNERS.get(self.tool_id)
        if owner is None or owner != self.agent:
            raise ValueError("conversation tool plan MUST name an owned pantheon tool")
        if not _is_finite_score(self.score) or self.score < 0:
            raise ValueError("conversation tool plan score MUST be finite and non-negative")
        if not isinstance(self.tier, str) or self.tier not in _PLAN_TIERS:
            raise ValueError("conversation tool plan tier MUST be canonical")
        if not isinstance(self.matched_terms, tuple) or any(
            not isinstance(term, str) for term in self.matched_terms
        ):
            raise ValueError("conversation tool plan matched_terms MUST be a string tuple")
        if len(self.matched_terms) > _MAX_MATCHED_TERMS or any(
            not term or len(term) > _MAX_PLAN_TERM_CHARS for term in self.matched_terms
        ):
            raise ValueError("conversation tool plan matched_terms MUST be bounded")


def plan_conversation_tools(
    requested_tool_ids: Sequence[str],
    *,
    agents: Sequence[str] = (),
    limit: int = MAX_TOOL_PLANS,
) -> tuple[ConversationToolPlan, ...]:
    """Project exact model-selected tool ids in canonical order.

    ``agents`` narrows the search to an already-routed set - the primary
    agent and any contributors - so tool selection refines a routing
    decision rather than competing with it. An empty sequence searches
    the whole pantheon, which is what a caller without a route has.

    Unknown, duplicate, cross-owner, or over-limit selections fail closed.
    """
    if limit <= 0 or isinstance(requested_tool_ids, str):
        return ()
    requested = tuple(requested_tool_ids)
    if len(requested) != len(set(requested)) or len(requested) > MAX_TOOL_PLANS:
        return ()
    wanted = frozenset(agents)
    plans: list[ConversationToolPlan] = []
    for index, tool_id in enumerate(requested):
        owner = _PLAN_OWNERS.get(tool_id)
        if owner is None or (wanted and owner not in wanted):
            return ()
        plans.append(
            ConversationToolPlan(
                agent=owner,
                tool_id=tool_id,
                score=float(len(requested) - index),
                matched_terms=(),
            )
        )
    return tuple(plans[: min(limit, MAX_TOOL_PLANS)])


__all__ = [
    "MAX_PLANNED_QUESTION_CHARS",
    "MAX_TOOL_PLANS",
    "PREFETCH_BUDGET_SECONDS",
    "ConversationToolPlan",
    "plan_conversation_tools",
]
