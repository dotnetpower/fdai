"""Decide which owned read tools a question needs, before any agent runs.

A charter tells its agent to "answer only from owned state through the
allowed tools", but nothing in the read path ever dispatched one, so the
instruction described a surface no turn could reach. This module closes
that gap from the outside: it picks the tools a question calls for, so a
caller can gather scoped evidence *before* the answering turn instead of
asking an agent to narrate what it might have looked at.

The choice is deterministic and needs no model. A tool already declares
everything the decision requires - its id, its purpose, and the fact keys
it yields - so matching the question against that declaration is a
lexical decision, not a judgement. That keeps the planner replayable: the
same question and the same catalog always select the same tools, which is
what an evidence-governed read path needs.

Dispatch stays one level deep. Planning happens outside the agent, and an
agent holds no reference to the tool registry, so there is no edge from a
turn back into a tool. :mod:`fdai.agents._framework.conversation_tools`
refuses a nested call as the second lock.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from fdai.agents._framework.pantheon import PANTHEON_SPECS
from fdai.agents._framework.tool_examples import TOOL_EXAMPLES

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

#: Distinct terms taken from one question. A long question cannot widen
#: the match surface without bound.
_MAX_QUESTION_TERMS: Final[int] = 64

#: Shortest term that may carry meaning. Two-letter fragments match
#: everything and would make every tool look relevant.
_MIN_TERM_CHARS: Final[int] = 3

#: Terms that appear in almost every tool declaration and almost every
#: operator question. Left in, they would score every tool equally and
#: turn ranking into declaration order.
_STOP_TERMS: Final[frozenset[str]] = frozenset(
    {
        "the",
        "and",
        "for",
        "read",
        "show",
        "list",
        "what",
        "which",
        "who",
        "how",
        "why",
        "when",
        "where",
        "current",
        "data",
        "agent",
        "fdai",
    }
)

_PLAN_TIERS: Final[frozenset[str]] = frozenset({"t0_lexical", "t1_semantic"})
_PLAN_OWNERS: Final[dict[str, str]] = {
    tool.tool_id: spec.name for spec in PANTHEON_SPECS for tool in spec.conversation.tool_specs
}
_MAX_PLAN_TERM_CHARS: Final[int] = 64


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
    tier: str = "t0_lexical"

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
        if len(self.matched_terms) > _MAX_QUESTION_TERMS or any(
            not term or len(term) > _MAX_PLAN_TERM_CHARS for term in self.matched_terms
        ):
            raise ValueError("conversation tool plan matched_terms MUST be bounded")


def plan_conversation_tools(
    question: str,
    *,
    agents: Sequence[str] = (),
    limit: int = MAX_TOOL_PLANS,
) -> tuple[ConversationToolPlan, ...]:
    """Return the tools ``question`` asks for, best match first.

    ``agents`` narrows the search to an already-routed set - the primary
    agent and any contributors - so tool selection refines a routing
    decision rather than competing with it. An empty sequence searches
    the whole pantheon, which is what a caller without a route has.

    Returns an empty tuple when nothing matches. That is the common case
    and the correct one: most questions are answered from the agent's own
    turn, and dispatching a tool nobody asked for spends a read budget to
    attach evidence for a different question.
    """
    if limit <= 0:
        return ()
    terms = _question_terms(question)
    if not terms:
        return ()
    wanted = frozenset(agents)
    scored: list[ConversationToolPlan] = []
    for spec in PANTHEON_SPECS:
        if wanted and spec.name not in wanted:
            continue
        for tool in spec.conversation.tool_specs:
            matched = tuple(sorted(terms & _tool_terms(tool.tool_id, tool.purpose, tool.fact_keys)))
            if not matched:
                continue
            scored.append(
                ConversationToolPlan(
                    agent=spec.name,
                    tool_id=tool.tool_id,
                    score=len(matched),
                    matched_terms=matched,
                )
            )
    if scored:
        strongest = max(_plan_term_weight(plan) for plan in scored)
        scored = [plan for plan in scored if _plan_term_weight(plan) >= strongest * 0.75]
    # Sorted by score, then by name: ties MUST NOT depend on catalog
    # order, or adding an unrelated tool would silently re-rank an
    # existing question's plan and a recorded turn would stop replaying.
    scored.sort(key=lambda plan: (-plan.score, plan.agent, plan.tool_id))
    return tuple(scored[: min(limit, MAX_TOOL_PLANS)])


def _iter_tokens(text: str) -> tuple[str, ...]:
    pieces: list[str] = []
    buffer: list[str] = []
    for ch in text.casefold():
        if ch.isalnum() or ch in {"_", "-"}:
            buffer.append(ch)
        elif buffer:
            if "".join(buffer):
                pieces.append("".join(buffer))
            buffer.clear()
    if buffer:
        pieces.append("".join(buffer))
    return tuple(pieces)


def _term_variants(token: str) -> tuple[str, ...]:
    normalized = token.strip("_-").casefold()
    if not normalized:
        return ()
    stripped = _strip_korean_particles(normalized)
    if stripped != normalized:
        return (stripped,)
    return (normalized,)


def _strip_korean_particles(token: str) -> str:
    particles = (
        "은",
        "는",
        "이",
        "가",
        "을",
        "를",
        "과",
        "와",
        "의",
        "도",
        "에",
        "에서",
        "한",
        "만",
        "께",
    )
    for particle in particles:
        if token.endswith(particle):
            stripped = token.removesuffix(particle)
            if stripped:
                return stripped
    return token


def _is_meaningful_term(term: str) -> bool:
    if not term:
        return False
    return len(term) >= _MIN_TERM_CHARS or (not term.isascii() and len(term) >= 2)


def _tool_terms(tool_id: str, purpose: str, fact_keys: Iterable[str]) -> frozenset[str]:
    examples = " ".join(term for pair in TOOL_EXAMPLES.get(tool_id, ()) for term in pair.split())
    source = " ".join((tool_id, purpose, *fact_keys, examples)).casefold()
    found: set[str] = set()
    for token in _iter_tokens(source):
        for term in _term_variants(token):
            if _is_meaningful_term(term) and term not in _STOP_TERMS:
                found.add(term)
    return frozenset(found)


def _plan_term_weight(plan: ConversationToolPlan) -> float:
    return sum(_term_specificity(term) for term in plan.matched_terms)


def _term_specificity(term: str) -> float:
    count = _TERM_CORPUS_FREQUENCIES.get(term, 1)
    if count <= 1:
        return 2.0
    if count <= 2:
        return 1.0
    if count <= 4:
        return 0.5
    return 0.25


_TERM_CORPUS_FREQUENCIES: Final[dict[str, int]] = {}
for spec in PANTHEON_SPECS:
    for tool in spec.conversation.tool_specs:
        for source in (
            " ".join((tool.tool_id, tool.purpose, *tool.fact_keys)),
            *TOOL_EXAMPLES.get(tool.tool_id, ()),
        ):
            for token in _iter_tokens(source):
                for term in _term_variants(token):
                    if _is_meaningful_term(term):
                        _TERM_CORPUS_FREQUENCIES[term] = _TERM_CORPUS_FREQUENCIES.get(term, 0) + 1


def _question_terms(question: str) -> frozenset[str]:
    if not question:
        return frozenset()
    found: set[str] = set()
    for token in _iter_tokens(question[:MAX_PLANNED_QUESTION_CHARS]):
        for term in _term_variants(token):
            if _is_meaningful_term(term) and term not in _STOP_TERMS:
                found.add(term)
            if len(found) >= _MAX_QUESTION_TERMS:
                return frozenset(tuple(found)[:_MAX_QUESTION_TERMS])
    return frozenset(found)


__all__ = [
    "MAX_PLANNED_QUESTION_CHARS",
    "MAX_TOOL_PLANS",
    "PREFETCH_BUDGET_SECONDS",
    "ConversationToolPlan",
    "plan_conversation_tools",
]
