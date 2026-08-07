"""Read-only adapter from Operator Console chat to the pantheon runtime."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from fdai.agents import PantheonRuntime
from fdai.core.conversation.answer_plan import AnswerIntent, AnswerSection, build_answer_plan
from fdai.core.conversation.answer_planning import (
    AnswerContribution,
    AnswerPlanningRoute,
    GroundedFact,
    PlanningCandidate,
)

_SAGA_DOMAIN = re.compile(r"\b(audit|history|issue|handoff)\b|감사|이력|인계|이슈", re.I)
_PLANNING_EXCLUDED = frozenset({"Bragi", "Norns", "Odin"})


@dataclass(frozen=True, slots=True)
class PantheonChatDelegate:
    """Route a web question through Bragi without conversational side effects."""

    runtime: PantheonRuntime

    def should_delegate(self, prompt: str, view_context: dict[str, Any]) -> bool:
        """Ask Bragi whether this turn needs agent-owned state beyond the screen."""
        return self.runtime.should_delegate_conversation(prompt, view_context)

    async def delegate(
        self,
        *,
        prompt: str,
        user_id: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        turn = await self.runtime.ask(
            session_id=_scoped_session_id(user_id, session_id),
            user_id=user_id,
            question=prompt,
            allow_action_proposal=False,
            materialize_handoff=False,
        )
        if turn is None or not isinstance(turn.answer, dict):
            return None
        answer = turn.answer.get("answer")
        primary = turn.answer.get("primary_agent")
        if not isinstance(primary, str):
            return None
        if not isinstance(answer, str) or not answer:
            abstain_reason = turn.answer.get("abstain_reason")
            if not isinstance(abstain_reason, str) or not abstain_reason:
                return None
            return {
                "primary_agent": "Bragi",
                "answer": None,
                "facts": {},
                "contributors": [],
                "contributor_answers": [],
                "trace_ref": str(turn.answer.get("trace_ref") or "")[:256],
                "handoff_from": primary,
                "handoff_reason": abstain_reason[:128],
            }
        facts = turn.answer.get("facts")
        evidence_refs = _delegate_evidence_refs(primary, facts, fallback=answer)
        conversation_policy = turn.answer.get("conversation_policy")
        prompt_composition = turn.answer.get("prompt_composition")
        contributors = turn.answer.get("contributors")
        contributor_answers = turn.answer.get("contributor_answers")
        return {
            "primary_agent": primary,
            "answer": answer,
            "facts": dict(facts) if isinstance(facts, dict) else {},
            "evidence_refs": list(evidence_refs),
            "conversation_policy": (
                dict(conversation_policy) if isinstance(conversation_policy, dict) else {}
            ),
            "prompt_composition": (
                dict(prompt_composition) if isinstance(prompt_composition, dict) else {}
            ),
            "contributors": (
                [item for item in contributors[:8] if isinstance(item, str)]
                if isinstance(contributors, list)
                else []
            ),
            "contributor_answers": (
                [dict(item) for item in contributor_answers[:8] if isinstance(item, dict)]
                if isinstance(contributor_answers, list)
                else []
            ),
            "trace_ref": str(turn.answer.get("trace_ref") or "")[:256],
        }

    def route_answer_planning(self, prompt: str) -> AnswerPlanningRoute:
        """Return a deterministic, read-only contributor route for shadow planning."""
        decision = self.runtime.route_conversation(prompt)
        if decision is None:
            return AnswerPlanningRoute(primary_agent=None, candidates=())
        primary = getattr(decision, "primary_agent", None)
        scores = getattr(decision, "scores", {})
        if not isinstance(scores, dict):
            return AnswerPlanningRoute(primary_agent=primary, candidates=())
        candidates = tuple(
            PlanningCandidate(agent=name, score=float(score))
            for name, score in scores.items()
            if _planning_candidate_allowed(name, prompt) and isinstance(score, int | float)
        )
        ranked = sorted((candidate.score for candidate in candidates), reverse=True)
        margin = ranked[0] - ranked[1] if len(ranked) >= 2 else None
        confidence = min(1.0, max(0.0, ranked[0] / 10.0)) if ranked else None
        return AnswerPlanningRoute(
            primary_agent=primary if isinstance(primary, str) else None,
            candidates=candidates,
            confidence=confidence,
            margin=margin,
        )

    async def contribute(
        self,
        *,
        agent: str,
        prompt: str,
        max_tokens: int,  # noqa: ARG002 - enforced by the core result boundary
    ) -> AnswerContribution | None:
        """Collect one typed contribution from an agent's read-only port."""
        if not _planning_candidate_allowed(agent, prompt):
            return None
        result = await self.runtime.contribute_conversation(
            agent,
            prompt,
        )
        if not isinstance(result, dict) or result.get("requires_typed_pipeline") is True:
            return None
        answer = result.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            return None
        facts = result.get("facts")
        grounded = _grounded_facts(agent, facts, fallback=answer)
        evidence_refs = tuple(dict.fromkeys(fact.evidence_ref for fact in grounded))
        if not evidence_refs:
            return None
        return AnswerContribution(
            agent=agent,
            facts=grounded,
            caveats=(),
            suggested_sections=_suggested_sections(prompt),
            evidence_refs=evidence_refs,
            confidence=_contribution_confidence(facts),
        )


def _scoped_session_id(user_id: str, session_id: str) -> str:
    digest = hashlib.sha256(f"{user_id}\0{session_id}".encode()).hexdigest()[:32]
    return f"web-{digest}"


def _planning_candidate_allowed(agent: str, prompt: str) -> bool:
    if agent in _PLANNING_EXCLUDED:
        return False
    if agent == "Saga" and _SAGA_DOMAIN.search(prompt) is None:
        return False
    return True


def _grounded_facts(
    agent: str,
    raw: object,
    *,
    fallback: str,
) -> tuple[GroundedFact, ...]:
    items = list(raw.items())[:32] if isinstance(raw, dict) else [("answer", fallback)]
    facts: list[GroundedFact] = []
    for key, value in items:
        rendered = json.dumps(value, sort_keys=True, ensure_ascii=True, default=str)
        claim = f"{key}={rendered}"[:2_000]
        digest = hashlib.sha256(f"{agent}\0{key}\0{rendered}".encode()).hexdigest()[:24]
        facts.append(
            GroundedFact(
                claim=claim,
                evidence_ref=f"agent-owned:{agent.lower()}:{digest}",
            )
        )
    return tuple(facts)


def _delegate_evidence_refs(
    agent: str,
    raw: object,
    *,
    fallback: str,
) -> tuple[str, ...]:
    if isinstance(raw, dict):
        explicit = raw.get("evidence_refs")
        if isinstance(explicit, list):
            refs = tuple(
                dict.fromkeys(
                    item
                    for item in explicit[:64]
                    if isinstance(item, str) and 0 < len(item) <= 1_024
                )
            )
            if refs:
                return refs
    return tuple(fact.evidence_ref for fact in _grounded_facts(agent, raw, fallback=fallback))


def _suggested_sections(prompt: str) -> tuple[AnswerSection, ...]:
    intent = build_answer_plan(prompt).intent
    if intent is AnswerIntent.WHY:
        return (AnswerSection.EVIDENCE, AnswerSection.CONSTRAINTS)
    if intent is AnswerIntent.COMPARISON:
        return (AnswerSection.TRADE_OFFS, AnswerSection.RECOMMENDATION)
    if intent is AnswerIntent.DIAGNOSIS:
        return (AnswerSection.HYPOTHESES, AnswerSection.CHECKS)
    return (AnswerSection.BOUNDED_ANSWER,)


def _contribution_confidence(facts: object) -> float:
    if isinstance(facts, dict):
        raw = facts.get("confidence")
        if isinstance(raw, int | float):
            return min(1.0, max(0.0, float(raw)))
    return 0.7


__all__ = ["PantheonChatDelegate"]
