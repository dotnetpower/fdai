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
import re
from collections.abc import Iterable, Sequence
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
        "state",
        "status",
        "data",
        "agent",
        "fdai",
    }
)

#: Operator vocabulary mapped onto the English terms a tool declares.
#:
#: FDAI is bilingual, but machine keys stay English: a tool id and its
#: fact keys are record keys, not prose, so they are not translated. That
#: leaves a Korean question with no term in common with any declaration,
#: and without this map every Korean question selects zero tools while
#: the same question in English selects three. Translating the question's
#: domain nouns is the small, deterministic half of the problem; it keeps
#: one English vocabulary to rank against.
#:
#: Only nouns that already appear in a tool declaration belong here. A
#: word that maps onto nothing cannot change a ranking, and pretending
#: otherwise would grow a catalog nobody can verify.
_TERM_TRANSLATIONS: Final[dict[str, tuple[str, ...]]] = {
    "승인": ("approval", "approvals"),
    "결재": ("approval", "approvals"),
    "대기": ("pending", "queue"),
    "정족수": ("quorum",),
    "비용": ("cost", "costs"),
    "예산": ("budget",),
    "요금": ("cost", "costs"),
    "용량": ("capacity",),
    "예측": ("forecast", "forecasts"),
    "사이징": ("sizing",),
    "권고": ("recommendation", "recommendations"),
    "롤백": ("rollback", "rollbacks"),
    "복구": ("recovery",),
    "실행": ("execution", "run", "runs"),
    "액션": ("action",),
    "이력": ("history",),
    "감사": ("audit",),
    "이슈": ("issue", "issues"),
    "인계": ("handoffs",),
    "판정": ("verdict", "verdicts"),
    "판단": ("judgment",),
    "근본원인": ("root", "cause", "rca"),
    "원인": ("cause", "rca"),
    "위험": ("risk",),
    "중재": ("arbitration", "arbitrations"),
    "우선순위": ("priority", "order"),
    "포트폴리오": ("portfolio",),
    "정책": ("policy",),
    "규칙": ("rule", "rules"),
    "카탈로그": ("catalog",),
    "후보": ("candidate", "candidates"),
    "관측": ("observations", "observed"),
    "보안": ("security",),
    "드리프트": ("drift",),
    "카오스": ("chaos",),
    "실험": ("experiment", "experiments"),
    "안전": ("safety",),
    "폭발반경": ("blast", "radius"),
    "복원력": ("resilience",),
    "패턴": ("pattern",),
    "유입": ("ingress",),
    "중복": ("dedup", "deduplication"),
    "케이스": ("case",),
    "역량": ("capability", "capabilities"),
    "라우팅": ("routing",),
    "리소스": ("resource", "resources"),
    "자원": ("resource", "resources"),
    "이벤트": ("event", "events"),
    "증거": ("evidence",),
}

_TERM = re.compile(r"[a-z0-9]+|[가-힣]+")
_PLAN_TIERS: Final[frozenset[str]] = frozenset({"t0_lexical", "t1_semantic"})
_PLAN_OWNERS: Final[dict[str, str]] = {
    tool.tool_id: spec.name for spec in PANTHEON_SPECS for tool in spec.conversation.tool_specs
}
_MAX_PLAN_TERM_CHARS: Final[int] = 64


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
        owner = _PLAN_OWNERS.get(self.tool_id)
        if owner is None or owner != self.agent:
            raise ValueError("conversation tool plan MUST name an owned pantheon tool")
        if not math.isfinite(self.score) or self.score < 0:
            raise ValueError("conversation tool plan score MUST be finite and non-negative")
        if self.tier not in _PLAN_TIERS:
            raise ValueError("conversation tool plan tier MUST be canonical")
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
    # Sorted by score, then by name: ties MUST NOT depend on catalog
    # order, or adding an unrelated tool would silently re-rank an
    # existing question's plan and a recorded turn would stop replaying.
    scored.sort(key=lambda plan: (-plan.score, plan.agent, plan.tool_id))
    return tuple(scored[: min(limit, MAX_TOOL_PLANS)])


def _question_terms(question: str) -> frozenset[str]:
    if not question:
        return frozenset()
    found: list[str] = []
    for match in _TERM.finditer(question.lower()[:MAX_PLANNED_QUESTION_CHARS]):
        term = match.group()
        translated = _translate(term)
        if translated:
            found.extend(translated)
        elif len(term) >= _MIN_TERM_CHARS and term not in _STOP_TERMS:
            found.append(term)
        if len(found) >= _MAX_QUESTION_TERMS:
            break
    return frozenset(found[:_MAX_QUESTION_TERMS])


def _translate(term: str) -> tuple[str, ...]:
    """Return the English terms a Korean word stands for.

    Korean is written without spaces between a noun and its particle, so
    an exact lookup misses '비용은' and '승인을'. Matching a known noun
    anywhere in the token handles that without a morphological analyser,
    which would be a dependency this decision does not need.
    """
    exact = _TERM_TRANSLATIONS.get(term)
    if exact is not None:
        return exact
    if term.isascii():
        return ()
    matched: list[str] = []
    for korean, english in _TERM_TRANSLATIONS.items():
        if korean in term:
            matched.extend(english)
    return tuple(matched)


def _tool_terms(tool_id: str, purpose: str, fact_keys: Iterable[str]) -> frozenset[str]:
    source = " ".join((tool_id, purpose, *fact_keys)).lower()
    return frozenset(
        term
        for term in _TERM.findall(source)
        if len(term) >= _MIN_TERM_CHARS and term not in _STOP_TERMS
    )


__all__ = [
    "MAX_PLANNED_QUESTION_CHARS",
    "MAX_TOOL_PLANS",
    "PREFETCH_BUDGET_SECONDS",
    "ConversationToolPlan",
    "plan_conversation_tools",
]
