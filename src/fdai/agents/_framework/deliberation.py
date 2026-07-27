"""Bounded read-only T1/T2 deliberation contracts for the Pantheon."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from fdai.agents._framework.base import AgentSpec
from fdai.agents._framework.bragi_models import RoutingDecision
from fdai.agents._framework.introspection import is_action_intent
from fdai.agents._framework.semantic_routing import SemanticAgentRouter
from fdai.rule_catalog.pipeline.distill.sensitivity import scan_text

_MAX_QUESTION_CHARS = 2_000
_MAX_ANSWER_CHARS = 16_000
_MAX_CLAIMS = 3
_MAX_PARTICIPANTS = 3
_MAX_T2_CONCLUSION_CHARS = 4_000
_MAX_TRACKED_CORRELATIONS = 1_024
_LOG = logging.getLogger(__name__)

CallResponder = Callable[
    [str, str, dict[str, Any]],
    Awaitable[tuple[dict[str, Any] | None, str | None]],
]


@dataclass(frozen=True, slots=True)
class EscalationBudget:
    """Pre-declared ceiling on conversational model escalation.

    ``cost-model.md`` requires the model budget to be a ceiling: overflow
    degrades to a cheaper path, never to uncapped inference. The
    conversational port had no such ceiling - T1 routing is free, but T2
    synthesis calls a model and nothing bounded how often.

    Both limits are deliberately small. A second synthesis on the same
    correlation re-reads the same bounded claims, so it buys presentation
    polish rather than evidence; the process-wide limit contains a
    runaway caller regardless of correlation.
    """

    max_calls_per_correlation: int = 1
    max_calls_total: int = 64

    def __post_init__(self) -> None:
        if self.max_calls_per_correlation < 0 or self.max_calls_total < 0:
            raise ValueError("escalation budget limits MUST be non-negative")
        if self.max_calls_per_correlation > self.max_calls_total:
            raise ValueError("per-correlation escalation budget MUST fit the total budget")
        if self.max_calls_total > _MAX_TRACKED_CORRELATIONS:
            # The ledger tracks per-correlation spend in a capped map. A
            # total budget larger than that cap would let an eviction drop
            # a spent correlation and silently refund its budget, so the
            # ceiling would not be a ceiling. Reject it instead.
            raise ValueError(
                "total escalation budget MUST NOT exceed "
                f"{_MAX_TRACKED_CORRELATIONS} tracked correlations"
            )


class EscalationLedger:
    """Deterministic, bounded accounting of conversational model calls.

    Pure in-process bookkeeping: the same call sequence always yields the
    same allow/deny decisions, so a recorded conversation replays. The
    correlation map is capped, because it is keyed by a value the caller
    supplies and would otherwise grow without bound.
    """

    def __init__(self, budget: EscalationBudget | None = None) -> None:
        self._budget = budget or EscalationBudget()
        self._per_correlation: dict[str, int] = {}
        self._total = 0

    @property
    def budget(self) -> EscalationBudget:
        return self._budget

    def allows(self, correlation_id: str) -> bool:
        if self._total >= self._budget.max_calls_total:
            return False
        spent = self._per_correlation.get(correlation_id, 0)
        return spent < self._budget.max_calls_per_correlation

    def record(self, correlation_id: str) -> None:
        """Charge one escalation, before the call rather than after.

        A provider call that then fails still consumed the budget it was
        granted; charging on success would let a failing provider be
        retried without limit.

        The map cannot overflow while budget remains: each charge adds at
        most one key and the total budget is capped at the map's size, so
        an eviction can never refund a correlation that still counts.
        """
        self._total += 1
        if len(self._per_correlation) >= _MAX_TRACKED_CORRELATIONS:
            self._per_correlation.pop(next(iter(self._per_correlation)))
        self._per_correlation[correlation_id] = self._per_correlation.get(correlation_id, 0) + 1

    def snapshot(self, correlation_id: str) -> dict[str, int]:
        """Return the bound an answer may state, with no provider detail."""
        return {
            "spent_for_correlation": self._per_correlation.get(correlation_id, 0),
            "max_per_correlation": self._budget.max_calls_per_correlation,
            "spent_total": self._total,
            "max_total": self._budget.max_calls_total,
        }


@dataclass(frozen=True, slots=True)
class DeliberationClaim:
    """One owner-attributed conversational claim with durable evidence refs."""

    agent: str
    answer: str
    evidence_refs: tuple[str, ...]
    prompt_sha256: str

    def __post_init__(self) -> None:
        if not self.agent or not self.answer or len(self.answer) > _MAX_ANSWER_CHARS:
            raise ValueError("deliberation claim MUST have a bounded agent and answer")
        if len(self.evidence_refs) > 20 or any(not ref for ref in self.evidence_refs):
            raise ValueError("deliberation claim evidence_refs MUST be bounded and non-empty")
        if len(self.prompt_sha256) != 64:
            raise ValueError("deliberation claim prompt_sha256 MUST be a SHA-256 digest")


@dataclass(frozen=True, slots=True)
class DeliberationRequest:
    """Server-owned input to a presentation-only T2 conversation synthesizer."""

    question: str
    requester: str
    correlation_id: str
    primary_agent: str
    claims: tuple[DeliberationClaim, ...]
    participant_prompts: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.question or len(self.question) > _MAX_QUESTION_CHARS:
            raise ValueError("deliberation question MUST be bounded and non-empty")
        if not self.requester or not self.primary_agent:
            raise ValueError("deliberation requester and primary_agent MUST be non-empty")
        if len(self.correlation_id) > 256:
            raise ValueError("deliberation correlation_id MUST be at most 256 characters")
        if not 2 <= len(self.claims) <= _MAX_CLAIMS:
            raise ValueError("deliberation requires between two and three claims")
        if len(self.participant_prompts) != len(self.claims):
            raise ValueError("deliberation prompts MUST align with claims")


class T2ConversationSynthesizer(Protocol):
    """Optional T2 synthesis seam with no typed decision or execution authority."""

    async def synthesize(self, request: DeliberationRequest) -> str | None:
        """Return one grounded presentation conclusion, or abstain."""


class ConversationDeliberator:
    """Orchestrate one T1 position/critique round and optional T2 synthesis."""

    def __init__(
        self,
        *,
        specs: Sequence[AgentSpec],
        semantic_router: SemanticAgentRouter | None,
        t2_synthesizer: T2ConversationSynthesizer | None,
        call_responder: CallResponder,
        escalation_budget: EscalationBudget | None = None,
    ) -> None:
        if not specs:
            raise ValueError("conversation deliberator requires agent specs")
        self._specs = {spec.name: spec for spec in specs}
        self._semantic_router = semantic_router
        self._t2_synthesizer = t2_synthesizer
        self._call_responder = call_responder
        self._ledger = EscalationLedger(escalation_budget)

    async def deliberate(
        self,
        *,
        question: str,
        requester: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        """Return a bounded presentation outcome without typed authority."""
        if len(question) > _MAX_QUESTION_CHARS:
            raise ValueError("question MUST be at most 2000 characters")
        if requester not in self._specs:
            raise ValueError(f"unknown requester agent: {requester!r}")
        if len(correlation_id) > 256:
            raise ValueError("correlation_id MUST be at most 256 characters")
        base = {
            "requester": requester,
            "trace_ref": correlation_id,
            "authority": "presentation_only",
            "rounds": [],
        }
        if is_action_intent(question):
            return {
                **base,
                "status": "abstain",
                "reason": "requires_typed_pipeline",
                "requires_typed_pipeline": True,
            }
        if self._semantic_router is None:
            return {**base, "status": "abstain", "reason": "t1_unavailable"}

        decision = await self._semantic_router.route(
            question,
            t0=RoutingDecision(primary_agent=None, scores={}, tie_break=None),
            max_contributors=_MAX_PARTICIPANTS - 1,
        )
        if decision.primary_agent is None or decision.method != "t1_semantic":
            return {**base, "status": "abstain", "reason": "t1_no_confident_route"}
        participants = (decision.primary_agent, *decision.contributors)[:_MAX_PARTICIPANTS]
        if len(participants) < 2:
            return {
                **base,
                "status": "abstain",
                "reason": "t1_insufficient_peers",
                "primary_agent": decision.primary_agent,
                "participants": list(participants),
            }

        primary_raw, primary_error = await self._call_responder(
            decision.primary_agent,
            question,
            {
                "requester": requester,
                "a2a": True,
                "correlation_id": correlation_id,
                "deliberation_phase": "position",
                "deliberation_tier": "T1",
                # Whether a model escalation is still affordable this turn,
                # and the bound itself. The agent states the bound rather
                # than implying a deeper pass ran when it never did.
                "escalation_available": self._ledger.allows(correlation_id),
                **self._escalation_counters(correlation_id),
            },
        )
        primary_claim = _claim(decision.primary_agent, primary_raw)
        if primary_claim is None:
            return {
                **base,
                "status": "abstain",
                "reason": primary_error or "primary_abstained",
                "primary_agent": decision.primary_agent,
                "participants": list(participants),
            }

        critiques = await asyncio.gather(
            *(
                self._critique(
                    peer,
                    question=question,
                    requester=requester,
                    correlation_id=correlation_id,
                    primary_claim=primary_claim,
                )
                for peer in participants[1:]
            )
        )
        peer_claims = tuple(claim for claim in critiques if claim is not None)
        if not peer_claims:
            return {
                **base,
                "status": "abstain",
                "reason": "peers_abstained",
                "primary_agent": decision.primary_agent,
                "participants": list(participants),
            }

        claims = (primary_claim, *peer_claims)
        result: dict[str, Any] = {
            **base,
            "status": "completed",
            "tier": "T1",
            "primary_agent": decision.primary_agent,
            "participants": [claim.agent for claim in claims],
            "rounds": [
                {"phase": "position", "contributions": [_claim_dict(primary_claim)]},
                {
                    "phase": "critique",
                    "contributions": [_claim_dict(claim) for claim in peer_claims],
                },
            ],
            "conclusion": primary_claim.answer,
            "semantic_score": decision.semantic_score,
            "semantic_margin": decision.semantic_margin,
        }
        if self._t2_synthesizer is None:
            return result
        return await self._synthesize(
            result,
            question=question,
            requester=requester,
            correlation_id=correlation_id,
            primary_agent=decision.primary_agent,
            claims=claims,
        )

    async def _critique(
        self,
        agent_name: str,
        *,
        question: str,
        requester: str,
        correlation_id: str,
        primary_claim: DeliberationClaim,
    ) -> DeliberationClaim | None:
        response, _ = await self._call_responder(
            agent_name,
            question,
            {
                "requester": requester,
                "a2a": True,
                "correlation_id": correlation_id,
                "deliberation_phase": "critique",
                "deliberation_tier": "T1",
                "peer_claims": (_claim_dict(primary_claim),),
                "escalation_available": self._ledger.allows(correlation_id),
                **self._escalation_counters(correlation_id),
                # The primary owns the conclusion; a critic contributes
                # owned evidence and hands the answer back to that owner.
                "handoff_owner": primary_claim.agent,
            },
        )
        return _claim(agent_name, response)

    def _escalation_counters(self, correlation_id: str) -> dict[str, int]:
        """Return the bound a turn may state, as bounded integers."""
        snapshot = self._ledger.snapshot(correlation_id)
        return {
            "escalation_spent": snapshot["spent_for_correlation"],
            "escalation_limit": snapshot["max_per_correlation"],
        }

    async def _synthesize(
        self,
        result: dict[str, Any],
        *,
        question: str,
        requester: str,
        correlation_id: str,
        primary_agent: str,
        claims: tuple[DeliberationClaim, ...],
    ) -> dict[str, Any]:
        synthesizer = self._t2_synthesizer
        if synthesizer is None:
            return result
        # The budget is a ceiling, not a target: when it is spent the round
        # stays at T1 rather than calling a model anyway. The bound is
        # reported so the answer can say the deeper pass did not run.
        if not self._ledger.allows(correlation_id):
            result["t2_status"] = "budget_denied"
            result["escalation_budget"] = self._ledger.snapshot(correlation_id)
            return result
        self._ledger.record(correlation_id)
        request = DeliberationRequest(
            question=question,
            requester=requester,
            correlation_id=correlation_id,
            primary_agent=primary_agent,
            claims=claims,
            participant_prompts=tuple(
                (claim.agent, self._specs[claim.agent].conversation.system_prompt)
                for claim in claims
            ),
        )
        try:
            conclusion = await synthesizer.synthesize(request)
        except Exception as exc:  # noqa: BLE001 - optional presentation degradation
            _LOG.warning(
                "pantheon_t2_deliberation_failed",
                extra={"error_type": type(exc).__name__},
            )
            result["t2_status"] = "error"
            return result
        if not isinstance(conclusion, str) or not conclusion.strip():
            result["t2_status"] = "abstained"
        elif len(conclusion) > _MAX_T2_CONCLUSION_CHARS:
            result["t2_status"] = "output_too_large"
        elif scan_text(conclusion):
            result["t2_status"] = "sensitive_output"
        else:
            result["tier"] = "T2"
            result["t2_status"] = "completed"
            result["conclusion"] = conclusion.strip()
        return result


def _claim(agent_name: str, response: dict[str, Any] | None) -> DeliberationClaim | None:
    if response is None or not isinstance(response.get("answer"), str):
        return None
    facts = response.get("facts")
    raw_refs = facts.get("evidence_refs") if isinstance(facts, dict) else None
    evidence_refs = (
        tuple(str(ref) for ref in raw_refs[:20] if str(ref))
        if isinstance(raw_refs, list | tuple)
        else ()
    )
    policy = response.get("conversation_policy")
    prompt_sha256 = policy.get("prompt_sha256") if isinstance(policy, dict) else None
    if not isinstance(prompt_sha256, str) or len(prompt_sha256) != 64:
        return None
    return DeliberationClaim(
        agent=agent_name,
        answer=response["answer"],
        evidence_refs=evidence_refs,
        prompt_sha256=prompt_sha256,
    )


def _claim_dict(claim: DeliberationClaim) -> dict[str, Any]:
    return {
        "agent": claim.agent,
        "answer": claim.answer,
        "evidence_refs": list(claim.evidence_refs),
        "prompt_sha256": claim.prompt_sha256,
    }


__all__ = [
    "ConversationDeliberator",
    "DeliberationClaim",
    "DeliberationRequest",
    "T2ConversationSynthesizer",
]
