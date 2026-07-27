"""Bounded read-only T1/T2 deliberation contracts for the Pantheon."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai.agents._framework.base import AgentSpec
from fdai.agents._framework.bragi_models import RoutingDecision
from fdai.agents._framework.introspection import is_action_intent
from fdai.agents._framework.semantic_routing import SemanticAgentRouter
from fdai.core.metering.budget import (
    BudgetChargingMeteringSink,
    BudgetLedger,
    InMemoryBudgetLedger,
    ModelBudget,
)
from fdai.core.metering.pricing import PricingTable
from fdai.core.metering.records import InvocationMode, InvocationScope, LlmInvocation
from fdai.core.metering.sink import MeteringSink
from fdai.core.metering.usage import TokenUsage
from fdai.rule_catalog.pipeline.distill.sensitivity import scan_text

_MAX_QUESTION_CHARS = 2_000
_MAX_ANSWER_CHARS = 16_000
_MAX_CLAIMS = 3
_MAX_PARTICIPANTS = 3
_MAX_T2_CONCLUSION_CHARS = 4_000
#: Same rough tokenizer the prompt composer uses, so an estimate here and
#: a layer budget there speak in one unit.
_CHARS_PER_TOKEN = 4
_T2_CONVERSATION_CAPABILITY = "t2.conversation.synthesis"
_CURRENCY = "USD"
_LOG = logging.getLogger(__name__)

CallResponder = Callable[
    [str, str, dict[str, Any]],
    Awaitable[tuple[dict[str, Any] | None, str | None]],
]


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


@dataclass(frozen=True, slots=True)
class SynthesisOutcome:
    """One T2 conclusion plus what it actually cost.

    The seam reports measured usage because a budget cannot meter what
    its provider never tells it. ``usage`` stays optional - a provider
    that does not report it is honestly unmeasured, and the call caps
    remain the fail-safe - but an implementation that can report MUST,
    so spend is grounded in real tokens rather than an estimate.
    """

    conclusion: str
    model_key: str = ""
    usage: TokenUsage | None = None


class T2ConversationSynthesizer(Protocol):
    """Optional T2 synthesis seam with no typed decision or execution authority."""

    async def synthesize(self, request: DeliberationRequest) -> SynthesisOutcome | None:
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
        escalation_budget: ModelBudget | None = None,
        escalation_ledger: BudgetLedger | None = None,
        pricing: PricingTable | None = None,
        metering: MeteringSink | None = None,
        t2_model_key: str = "",
    ) -> None:
        if not specs:
            raise ValueError("conversation deliberator requires agent specs")
        self._specs = {spec.name: spec for spec in specs}
        self._semantic_router = semantic_router
        self._t2_synthesizer = t2_synthesizer
        self._call_responder = call_responder
        self._budget = escalation_budget or ModelBudget()
        self._ledger: BudgetLedger = escalation_ledger or InMemoryBudgetLedger(self._budget)
        self._pricing = pricing
        # Wrap here, not at the caller: the ledger is built inside this
        # constructor, so a composition root cannot share it without
        # reaching into the deliberator. Wrapping internally makes the
        # metering write the single charge point by construction, and a
        # plain sink handed in from outside still bounds the money.
        self._metering: MeteringSink | None = (
            BudgetChargingMeteringSink(metering, self._ledger) if metering is not None else None
        )
        self._t2_model_key = t2_model_key

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
                "escalation_available": await self._ledger.allows(correlation_id),
                **await self._escalation_counters(correlation_id),
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
                "escalation_available": await self._ledger.allows(correlation_id),
                **await self._escalation_counters(correlation_id),
                # The primary owns the conclusion; a critic contributes
                # owned evidence and hands the answer back to that owner.
                "handoff_owner": primary_claim.agent,
            },
        )
        return _claim(agent_name, response)

    async def _escalation_counters(self, correlation_id: str) -> dict[str, int]:
        """Return the bound a turn may state, as bounded integers."""
        spend = await self._ledger.spend(correlation_id)
        return {
            "escalation_spent": spend.calls,
            "escalation_limit": self._budget.max_calls_per_correlation,
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
        budget_key = _budget_key(correlation_id, question=question, primary=primary_agent)
        if not await self._ledger.allows(budget_key):
            result["t2_status"] = "budget_denied"
            result["escalation_budget"] = await self._budget_snapshot(budget_key)
            return result
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
        # Charge the call before making it: a provider that then fails
        # still consumed what it was granted, so charging on success would
        # let a failing provider be retried without limit. Cost is charged
        # where it becomes known - the metering record - so this ledger has
        # exactly one place that accounts for money.
        await self._ledger.charge(budget_key, calls=1, cost_microusd=0)
        try:
            outcome = await synthesizer.synthesize(request)
        except Exception as exc:  # noqa: BLE001 - optional presentation degradation
            _LOG.warning(
                "pantheon_t2_deliberation_failed",
                extra={"error_type": type(exc).__name__},
            )
            result["t2_status"] = "error"
            return result
        conclusion = outcome.conclusion if isinstance(outcome, SynthesisOutcome) else None
        if isinstance(outcome, SynthesisOutcome):
            await self._meter(outcome, correlation_id=budget_key)
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
        result["escalation_budget"] = await self._budget_snapshot(budget_key)
        return result

    async def _budget_snapshot(self, correlation_id: str) -> dict[str, int]:
        """Return the bound an answer may state, with no provider detail."""
        spend = await self._ledger.spend(correlation_id)
        snapshot = {
            "spent_for_correlation": spend.calls,
            "max_per_correlation": self._budget.max_calls_per_correlation,
            "cost_microusd_for_correlation": spend.cost_microusd,
        }
        # An undeclared money limb is absent, not zero: reporting a bound
        # nobody declared would let an answer state a ceiling that does
        # not exist.
        cost_bound = self._budget.max_cost_microusd_per_correlation
        if cost_bound is not None:
            snapshot["max_cost_microusd_per_correlation"] = cost_bound
        return snapshot

    async def _meter(self, outcome: SynthesisOutcome, *, correlation_id: str) -> None:
        """Record the measured call so the spend is auditable and charged.

        An unmeasured provider is honestly unmeasured: nothing is
        recorded, because metering is for measured facts, and the call
        caps remain the bound.
        """
        if self._metering is None or outcome.usage is None or not outcome.model_key:
            return
        await self._metering.record(
            LlmInvocation(
                occurred_at=datetime.now(UTC),
                correlation_id=correlation_id,
                capability_id=_T2_CONVERSATION_CAPABILITY,
                model_key=outcome.model_key,
                tier="T2",
                mode=InvocationMode.SHADOW,
                usage=outcome.usage,
                usage_scope=InvocationScope.OPERATOR_CHAT,
                cost=(
                    self._pricing.cost_of(model_key=outcome.model_key, usage=outcome.usage)
                    if self._pricing is not None
                    else None
                ),
                currency=_CURRENCY if self._pricing is not None else None,
            )
        )


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


def _budget_key(correlation_id: str, *, question: str, primary: str) -> str:
    """Return the unit of work a deliberation charges its budget to.

    A correlation id is the right key when the caller supplies one. When
    it does not, every deliberation would otherwise share the empty
    string, so one synthesis would spend the budget of every unrelated
    question that followed it. Fall back to a stable digest of what the
    round is actually about: re-asking the same question of the same
    owner still costs nothing more, and a different question gets its own
    ceiling. Deterministic, so a recorded conversation replays.
    """
    if correlation_id:
        return correlation_id
    digest = hashlib.sha256(f"{primary}\n{question}".encode()).hexdigest()
    return f"unattributed:{digest[:32]}"
