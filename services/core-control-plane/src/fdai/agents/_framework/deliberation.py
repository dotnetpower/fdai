"""Bounded read-only T1/T2 deliberation contracts for the Pantheon."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from fdai.agents._framework.base import AgentSpec
from fdai.agents._framework.bragi_constants import _MAX_ANSWER_CHARS, _MAX_QUESTION_CHARS
from fdai.agents._framework.bragi_models import RoutingDecision
from fdai.agents._framework.deliberation_evaluation import (
    DeliberationSignal,
    evaluate_peer_claim,
    evaluate_t1_answers,
    evaluation_signals,
)
from fdai.agents._framework.introspection import durable_evidence_refs
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

_MAX_CLAIMS = 3
_MAX_PARTICIPANTS = 3
_MAX_T2_CONCLUSION_CHARS = 4_000
_T2_SYNTHESIS_TIMEOUT_SECONDS = 8.0
_FIXED_ASSURANCE_SCENARIO_ID = "conversation-assurance-census-v1"
#: Same rough tokenizer the prompt composer uses, so an estimate here and
#: a layer budget there speak in one unit.
_CHARS_PER_TOKEN = 4
_T2_CONVERSATION_CAPABILITY = "t2.conversation.synthesis"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
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
    evaluation_signals: tuple[DeliberationSignal, ...] = ()
    facts_json: str = "{}"

    def __post_init__(self) -> None:
        if not self.agent or not self.answer or len(self.answer) > _MAX_ANSWER_CHARS:
            raise ValueError("deliberation claim MUST have a bounded agent and answer")
        if (
            not self.evidence_refs
            or len(self.evidence_refs) > 20
            or any(not ref for ref in self.evidence_refs)
        ):
            raise ValueError("deliberation claim evidence_refs MUST be bounded and non-empty")
        if _SHA256.fullmatch(self.prompt_sha256) is None:
            raise ValueError("deliberation claim prompt_sha256 MUST be a SHA-256 digest")
        if len(self.facts_json.encode()) > 16_384:
            raise ValueError("deliberation owned facts MUST fit 16384 bytes")
        facts = json.loads(self.facts_json)
        if (
            not isinstance(facts, dict)
            or json.dumps(
                facts, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
            )
            != self.facts_json
        ):
            raise ValueError("deliberation owned facts MUST be canonical object JSON")


@dataclass(frozen=True, slots=True)
class DeliberationRequest:
    """Server-owned input to a presentation-only T2 conversation synthesizer."""

    question: str
    requester: str
    correlation_id: str
    primary_agent: str
    claims: tuple[DeliberationClaim, ...]
    participant_prompts: tuple[tuple[str, str], ...]
    locale: str = "en"
    purpose: Literal["discussion", "owned_answer"] = "discussion"

    def __post_init__(self) -> None:
        if not self.question or len(self.question) > _MAX_QUESTION_CHARS:
            raise ValueError("deliberation question MUST be bounded and non-empty")
        if not self.requester or not self.primary_agent:
            raise ValueError("deliberation requester and primary_agent MUST be non-empty")
        if len(self.correlation_id) > 256:
            raise ValueError("deliberation correlation_id MUST be at most 256 characters")
        if self.purpose not in {"discussion", "owned_answer"}:
            raise ValueError("conversation writing purpose is invalid")
        if not (1 if self.purpose == "owned_answer" else 2) <= len(self.claims) <= _MAX_CLAIMS:
            raise ValueError("deliberation requires between two and three claims")
        if self.primary_agent != self.claims[0].agent:
            raise ValueError("deliberation primary_agent MUST own the first claim")
        claim_agents = tuple(claim.agent for claim in self.claims)
        if len(claim_agents) != len(set(claim_agents)):
            raise ValueError("deliberation claim agents MUST be unique")
        if len(self.participant_prompts) != len(self.claims):
            raise ValueError("deliberation prompts MUST align with claims")
        prompt_agents = tuple(agent for agent, _ in self.participant_prompts)
        if prompt_agents != claim_agents:
            raise ValueError("deliberation prompts MUST align with claim agents")
        if self.locale not in {"en", "ko"}:
            raise ValueError("deliberation locale MUST be en or ko")

    @property
    def sha256(self) -> str:
        material = json.dumps(
            {
                "question": self.question,
                "requester": self.requester,
                "correlation_id": self.correlation_id,
                "primary_agent": self.primary_agent,
                "claims": [_claim_dict(claim) for claim in self.claims],
                "participant_prompts": self.participant_prompts,
                "locale": self.locale,
                **({"purpose": self.purpose} if self.purpose != "discussion" else {}),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(material.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class SynthesisOutcome:
    """One attributed T2 conclusion plus what it actually cost.

    The seam reports measured usage because a budget cannot meter what
    its provider never tells it. ``usage`` stays optional - a provider
    that does not report it is honestly unmeasured, and the call caps
    remain the fail-safe - but an implementation that can report MUST,
    so spend is grounded in real tokens rather than an estimate.
    """

    conclusion: str
    model_identity: str
    model_family: str
    model_key: str = ""
    usage: TokenUsage | None = None

    def __post_init__(self) -> None:
        if not self.model_identity.strip() or not self.model_family.strip():
            raise ValueError("T2 synthesis model identity and family MUST be non-empty")


class T2ConversationSynthesizer(Protocol):
    """Optional T2 synthesis seam with no typed decision or execution authority."""

    async def synthesize(self, request: DeliberationRequest) -> SynthesisOutcome | None:
        """Return one grounded presentation conclusion, or abstain."""


@dataclass(frozen=True, slots=True)
class SynthesisVerification:
    """Independent claim-verification receipt bound to the exact source and answer."""

    accepted: bool
    request_sha256: str
    conclusion_sha256: str
    evidence_refs: tuple[str, ...]
    verifier_identity: str


class ConversationSynthesisVerifier(Protocol):
    """Composition-owned V-CLAIM and independent entailment review boundary."""

    async def verify(
        self, request: DeliberationRequest, outcome: SynthesisOutcome
    ) -> SynthesisVerification | None: ...


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
        synthesis_verifier: ConversationSynthesisVerifier | None = None,
        synthesis_timeout_seconds: float = _T2_SYNTHESIS_TIMEOUT_SECONDS,
    ) -> None:
        if not specs:
            raise ValueError("conversation deliberator requires agent specs")
        if synthesis_verifier is not None and id(synthesis_verifier) == id(t2_synthesizer):
            raise ValueError("conversation synthesis requires an independent verifier")
        if (
            isinstance(synthesis_timeout_seconds, bool)
            or not isinstance(synthesis_timeout_seconds, int | float)
            or synthesis_timeout_seconds <= 0
        ):
            raise ValueError("synthesis_timeout_seconds MUST be positive")
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
        self._synthesis_verifier = synthesis_verifier
        self._synthesis_timeout_seconds = float(synthesis_timeout_seconds)

    async def deliberate(
        self,
        *,
        question: str,
        requester: str,
        correlation_id: str = "",
        locale: str = "en",
        allow_t2: bool = True,
        routing_decision: RoutingDecision | None = None,
        fixed_assurance_facts: Mapping[str, Mapping[str, object]] | None = None,
        fixed_assurance_scenario_id: str | None = None,
    ) -> dict[str, Any]:
        """Return a bounded presentation outcome without typed authority."""
        if type(allow_t2) is not bool:
            raise ValueError("allow_t2 MUST be a boolean")
        if len(question) > _MAX_QUESTION_CHARS:
            raise ValueError("question MUST be at most 2000 characters")
        if requester not in self._specs:
            raise ValueError(f"unknown requester agent: {requester!r}")
        if len(correlation_id) > 256:
            raise ValueError("correlation_id MUST be at most 256 characters")
        scenario_signals = _trusted_scenario_signals(
            fixed_assurance_facts
            if fixed_assurance_scenario_id == _FIXED_ASSURANCE_SCENARIO_ID
            else None,
            known_agents=set(self._specs),
        )
        base: dict[str, Any] = {
            "requester": requester,
            "trace_ref": correlation_id,
            "authority": "presentation_only",
            "rounds": [],
        }
        if self._semantic_router is None and routing_decision is None:
            return {**base, "status": "abstain", "reason": "t1_unavailable"}

        decision = routing_decision
        if decision is None or decision.primary_agent is None:
            if self._semantic_router is None:
                return {**base, "status": "abstain", "reason": "t1_no_confident_route"}
            decision = await self._semantic_router.route(
                question,
                t0=RoutingDecision(primary_agent=None, scores={}, tie_break=None),
                max_contributors=_MAX_PARTICIPANTS - 1,
            )
        if decision.primary_agent is None:
            return {**base, "status": "abstain", "reason": "t1_no_confident_route"}
        primary_agent = decision.primary_agent
        contributors = tuple(
            candidate
            for index, candidate in enumerate(decision.contributors)
            if candidate != primary_agent and candidate not in decision.contributors[:index]
        )[: _MAX_PARTICIPANTS - 1]
        scores = decision.scores
        if not contributors and self._semantic_router is not None:
            supplemental = await self._semantic_router.route(
                question,
                t0=RoutingDecision(primary_agent=None, scores={}, tie_break=None),
                max_contributors=_MAX_PARTICIPANTS - 1,
            )
            peer_candidates = (supplemental.primary_agent, *supplemental.contributors)
            contributors = tuple(
                candidate
                for index, candidate in enumerate(peer_candidates)
                if candidate is not None
                and candidate != primary_agent
                and candidate not in peer_candidates[:index]
            )[: _MAX_PARTICIPANTS - 1]
            scores = {**supplemental.scores, **scores}
        decision = RoutingDecision(
            primary_agent=primary_agent,
            scores=scores,
            tie_break=decision.tie_break,
            contributors=contributors,
            method=decision.method,
            semantic_score=decision.semantic_score,
            semantic_margin=decision.semantic_margin,
            provider_status=decision.provider_status,
        )
        base["routing_method"] = decision.method
        participants = (primary_agent, *decision.contributors)[:_MAX_PARTICIPANTS]
        base["requested_participants"] = list(participants)
        base["participant_outcomes"] = [
            {"agent": agent, "status": "not_attempted"} for agent in participants
        ]
        if len(participants) < 2:
            return {
                **base,
                "status": "abstain",
                "reason": "t1_insufficient_peers",
                "primary_agent": primary_agent,
                "participants": list(participants),
            }

        budget_key = _budget_key(
            correlation_id,
            question=question,
            primary=primary_agent,
        )
        primary_raw, primary_error = await self._call_responder(
            primary_agent,
            question,
            {
                "requester": requester,
                "a2a": True,
                "correlation_id": correlation_id,
                "locale": locale,
                "deliberation_phase": "position",
                "deliberation_tier": "T1",
                # Whether a model escalation is still affordable this turn,
                # and the bound itself. The agent states the bound rather
                # than implying a deeper pass ran when it never did.
                "escalation_available": await self._ledger.allows(budget_key),
                **await self._escalation_counters(budget_key),
            },
        )
        primary_claim = _claim(primary_agent, primary_raw)
        base["participant_outcomes"][0] = {
            "agent": primary_agent,
            "status": "completed" if primary_claim is not None else "abstained",
            "reason": None if primary_claim is not None else primary_error or "primary_abstained",
        }
        if primary_claim is None:
            return {
                **base,
                "status": "abstain",
                "reason": primary_error or "primary_abstained",
                "primary_agent": primary_agent,
                "participants": list(participants),
            }
        primary_claim = _with_scenario_signals(primary_claim, scenario_signals)

        critiques = await asyncio.gather(
            *(
                self._critique(
                    peer,
                    question=question,
                    requester=requester,
                    correlation_id=correlation_id,
                    locale=locale,
                    budget_key=budget_key,
                    primary_claim=primary_claim,
                )
                for peer in participants[1:]
            )
        )
        base["participant_outcomes"] = [
            base["participant_outcomes"][0],
            *(
                {
                    "agent": agent,
                    "status": "completed" if claim is not None else "abstained",
                    "reason": reason,
                }
                for agent, (claim, reason) in zip(participants[1:], critiques, strict=True)
            ),
        ]
        peer_claims = tuple(
            _with_scenario_signals(claim, scenario_signals)
            for claim, _reason in critiques
            if claim is not None
        )
        if not peer_claims:
            return {
                **base,
                "status": "abstain",
                "reason": "peers_abstained",
                "primary_agent": primary_agent,
                "participants": list(participants),
            }

        claims = (primary_claim, *peer_claims)
        result: dict[str, Any] = {
            **base,
            "status": "completed",
            "tier": "T1",
            "primary_agent": primary_agent,
            "participants": [claim.agent for claim in claims],
            "rounds": [
                {"phase": "position", "contributions": [_claim_dict(primary_claim)]},
                {
                    "phase": "critique",
                    "contributions": [
                        {
                            **_claim_dict(claim),
                            "peer_review": evaluate_peer_claim(primary_claim, claim),
                        }
                        for claim in peer_claims
                    ],
                },
            ],
            "conclusion": primary_claim.answer,
            "semantic_score": decision.semantic_score,
            "semantic_margin": decision.semantic_margin,
        }
        evaluation = evaluate_t1_answers(claims)
        result["t1_evaluation"] = evaluation.to_mapping()
        if len(peer_claims) != len(participants) - 1:
            result["status"] = "partial"
            result["reason"] = "participant_evidence_incomplete"
            result["conclusion"] = None
            result["t2_status"] = "held_incomplete_participants"
            return result
        if not evaluation.requires_t2:
            result["t2_status"] = "not_required"
            return result
        result["status"] = "held"
        result["reason"] = "structured_conflict_unresolved"
        result["conclusion"] = None
        if not allow_t2:
            result["t2_status"] = "disabled_by_request"
            return result
        if self._t2_synthesizer is None:
            result["t2_status"] = "unavailable"
            return result
        return await self.synthesize_answer(
            result,
            question=question,
            requester=requester,
            correlation_id=correlation_id,
            budget_key=budget_key,
            primary_agent=primary_agent,
            claims=claims,
            locale=locale,
        )

    async def _critique(
        self,
        agent_name: str,
        *,
        question: str,
        requester: str,
        correlation_id: str,
        locale: str,
        budget_key: str,
        primary_claim: DeliberationClaim,
    ) -> tuple[DeliberationClaim | None, str | None]:
        response, error = await self._call_responder(
            agent_name,
            question,
            {
                "requester": requester,
                "a2a": True,
                "correlation_id": correlation_id,
                "locale": locale,
                "deliberation_phase": "critique",
                "deliberation_tier": "T1",
                "peer_claims": (_claim_dict(primary_claim),),
                "escalation_available": await self._ledger.allows(budget_key),
                **await self._escalation_counters(budget_key),
                # The primary owns the conclusion; a critic contributes
                # owned evidence and hands the answer back to that owner.
                "handoff_owner": primary_claim.agent,
            },
        )
        claim = _claim(agent_name, response)
        return claim, None if claim is not None else error or "peer_abstained"

    async def _escalation_counters(self, correlation_id: str) -> dict[str, int]:
        """Return the bound a turn may state, as bounded integers."""
        spend = await self._ledger.spend(correlation_id)
        return {
            "escalation_spent": spend.calls,
            "escalation_limit": self._budget.max_calls_per_correlation,
        }

    async def synthesize_answer(
        self,
        result: dict[str, Any],
        *,
        question: str,
        requester: str,
        correlation_id: str,
        budget_key: str,
        primary_agent: str,
        claims: tuple[DeliberationClaim, ...],
        locale: str,
        purpose: Literal["discussion", "owned_answer"] = "discussion",
    ) -> dict[str, Any]:
        synthesizer = self._t2_synthesizer
        if synthesizer is None:
            return result
        verifier = self._synthesis_verifier
        if verifier is None:
            result["t2_status"] = "verification_unavailable"
            return result
        # The budget is a ceiling, not a target: when it is spent the round
        # stays at T1 rather than calling a model anyway. The bound is
        # reported so the answer can say the deeper pass did not run.
        # Reserve, do not ask-then-take: two turns of the same correlation
        # that both read the remaining allowance would both proceed, and a
        # ceiling of one call would admit however many happen to overlap.
        # The reservation is made before the call, so a provider that then
        # fails still consumed what it was granted. Cost is charged where
        # it becomes known - the metering record - so this ledger has
        # exactly one place that accounts for money.
        required_calls = getattr(synthesizer, "model_calls_per_synthesis", 1)
        if type(required_calls) is not int or not 1 <= required_calls <= 2:
            result["t2_status"] = "invalid_model_call_budget"
            return result
        if not await self._ledger.reserve(budget_key, calls=required_calls, cost_microusd=0):
            result["t2_status"] = "budget_denied"
            result["escalation_budget"] = await self._budget_snapshot(budget_key)
            return result
        request = DeliberationRequest(
            question=question,
            requester=requester,
            correlation_id=correlation_id,
            primary_agent=primary_agent,
            claims=claims,
            locale=locale,
            purpose=purpose,
            participant_prompts=tuple(
                (claim.agent, self._specs[claim.agent].conversation.system_prompt)
                for claim in claims
            ),
        )
        try:
            outcome = await asyncio.wait_for(
                synthesizer.synthesize(request),
                timeout=self._synthesis_timeout_seconds,
            )
        except TimeoutError:
            _LOG.warning("pantheon_t2_deliberation_timeout")
            result["t2_status"] = "timeout"
            result["escalation_budget"] = await self._budget_snapshot(budget_key)
            return result
        except Exception as exc:  # noqa: BLE001 - optional presentation degradation
            _LOG.warning(
                "pantheon_t2_deliberation_failed",
                extra={"error_type": type(exc).__name__},
            )
            result["t2_status"] = "error"
            # The call was charged before it was made, so the bound moved:
            # a turn that reports no bound after spending one would let an
            # answer imply the budget is untouched.
            result["escalation_budget"] = await self._budget_snapshot(budget_key)
            return result
        conclusion = outcome.conclusion if isinstance(outcome, SynthesisOutcome) else None
        if isinstance(outcome, SynthesisOutcome):
            result["t2_model_family"] = outcome.model_family
            result["t2_model_identity"] = outcome.model_identity
            metering_receipt_digest = await self._meter(outcome, correlation_id=budget_key)
            if metering_receipt_digest is not None:
                result["metering_receipt_digest"] = metering_receipt_digest
        if (
            not isinstance(outcome, SynthesisOutcome)
            or not isinstance(conclusion, str)
            or not conclusion.strip()
        ):
            result["t2_status"] = "abstained"
        elif len(conclusion) > _MAX_T2_CONCLUSION_CHARS:
            result["t2_status"] = "output_too_large"
        elif scan_text(conclusion):
            result["t2_status"] = "sensitive_output"
        else:
            try:
                verification = await asyncio.wait_for(
                    verifier.verify(request, outcome), timeout=self._synthesis_timeout_seconds
                )
            except TimeoutError:
                result["t2_status"] = "verification_timeout"
            except Exception as exc:  # noqa: BLE001 - fail-closed presentation boundary
                _LOG.warning(
                    "pantheon_synthesis_verification_failed",
                    extra={"error_type": type(exc).__name__, "correlation_id": correlation_id},
                )
                result["t2_status"] = "verification_error"
            else:
                evidence_refs = tuple(
                    sorted({ref for claim in claims for ref in claim.evidence_refs})
                )
                conclusion_sha256 = hashlib.sha256(conclusion.encode()).hexdigest()
                if (
                    not isinstance(verification, SynthesisVerification)
                    or type(verification.accepted) is not bool
                    or verification.request_sha256 != request.sha256
                    or verification.conclusion_sha256 != conclusion_sha256
                    or verification.evidence_refs != evidence_refs
                    or not isinstance(verification.verifier_identity, str)
                    or not verification.verifier_identity.strip()
                    or len(verification.verifier_identity) > 256
                    or verification.verifier_identity.strip().casefold()
                    == outcome.model_identity.strip().casefold()
                ):
                    result["t2_status"] = "verification_invalid"
                elif not verification.accepted:
                    result["t2_status"] = "verification_rejected"
                else:
                    result["status"] = "completed"
                    result.pop("reason", None)
                    result["tier"] = "T2"
                    result["t2_status"] = "completed"
                    result["conclusion"] = conclusion
                    result["synthesis_verification"] = {
                        "request_sha256": request.sha256,
                        "conclusion_sha256": conclusion_sha256,
                        "evidence_refs": list(evidence_refs),
                    }
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

    async def _meter(self, outcome: SynthesisOutcome, *, correlation_id: str) -> str | None:
        """Record the measured call so the spend is auditable and charged.

        An unmeasured provider is honestly unmeasured: nothing is
        recorded, because metering is for measured facts, and the call
        caps remain the bound.

        Best-effort, like ``MeteringEmitter.emit_safe``: the model has
        already answered and the call has already been charged, so a
        metering hiccup degrades the audit trail, never the operator's
        answer. The charging sink still charges what it could not write.
        """
        sink = self._metering
        if sink is None or outcome.usage is None or not outcome.model_key:
            return None
        # The currency is whatever the price list says it is. A fork may
        # price in its own currency, so stamping USD on a KRW price would
        # put a number in the audit trail that means something else.
        pricing = (
            self._pricing.pricing_for(outcome.model_key) if self._pricing is not None else None
        )
        invocation = LlmInvocation(
            occurred_at=datetime.now(UTC),
            correlation_id=correlation_id,
            capability_id=_T2_CONVERSATION_CAPABILITY,
            model_key=outcome.model_key,
            tier="T2",
            mode=InvocationMode.SHADOW,
            usage=outcome.usage,
            usage_scope=InvocationScope.OPERATOR_CHAT,
            cost=pricing.cost_of(outcome.usage) if pricing is not None else None,
            currency=pricing.currency if pricing is not None else None,
        )
        try:
            await sink.record(invocation)
        except Exception:  # noqa: BLE001 - metering is a side-channel
            _LOG.warning(
                "pantheon_t2_metering_failed",
                extra={"correlation_id": correlation_id},
            )
            return None
        material = json.dumps(
            {
                "capability_id": invocation.capability_id,
                "correlation_id": invocation.correlation_id,
                "model_key": invocation.model_key,
                "prompt_tokens": invocation.usage.prompt_tokens,
                "completion_tokens": invocation.usage.completion_tokens,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(material.encode()).hexdigest()


def _claim(agent_name: str, response: dict[str, Any] | None) -> DeliberationClaim | None:
    if response is None or not isinstance(response.get("answer"), str):
        return None
    facts = response.get("facts")
    raw_refs = facts.get("evidence_refs") if isinstance(facts, dict) else None
    evidence_refs = durable_evidence_refs(raw_refs, agent_name=agent_name)
    if not evidence_refs:
        return None
    composition = response.get("prompt_composition")
    prompt_sha256 = composition.get("prompt_sha256") if isinstance(composition, dict) else None
    if not isinstance(prompt_sha256, str) or _SHA256.fullmatch(prompt_sha256) is None:
        return None
    try:
        return DeliberationClaim(
            agent=agent_name,
            answer=response["answer"],
            evidence_refs=evidence_refs,
            prompt_sha256=prompt_sha256,
            evaluation_signals=evaluation_signals(facts),
            facts_json=json.dumps(
                facts, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
            ),
        )
    except (TypeError, ValueError):
        return None


def _trusted_scenario_signals(
    facts_by_agent: Mapping[str, Mapping[str, object]] | None,
    *,
    known_agents: set[str],
) -> dict[str, tuple[DeliberationSignal, ...]] | None:
    """Validate server-owned diagnostic facts before deriving T1 signals."""

    if facts_by_agent is None:
        return None
    if len(facts_by_agent) > len(known_agents) or any(
        agent not in known_agents for agent in facts_by_agent
    ):
        raise ValueError("trusted scenario facts contain an unknown agent")
    return {agent: evaluation_signals(facts) for agent, facts in facts_by_agent.items()}


def _with_scenario_signals(
    claim: DeliberationClaim,
    scenario_signals: Mapping[str, tuple[DeliberationSignal, ...]] | None,
) -> DeliberationClaim:
    if scenario_signals is None:
        return claim
    return replace(
        claim,
        evaluation_signals=scenario_signals.get(claim.agent, ()),
    )


def _claim_dict(claim: DeliberationClaim) -> dict[str, Any]:
    return {
        "agent": claim.agent,
        "answer": claim.answer,
        "evidence_refs": list(claim.evidence_refs),
        "prompt_sha256": claim.prompt_sha256,
        "facts": json.loads(claim.facts_json),
    }


__all__ = [
    "ConversationDeliberator",
    "ConversationSynthesisVerifier",
    "DeliberationClaim",
    "DeliberationRequest",
    "SynthesisVerification",
    "T2ConversationSynthesizer",
]


def _budget_key(correlation_id: str, *, question: str, primary: str) -> str:
    """Return the unit of work a deliberation charges its budget to."""
    if correlation_id:
        return correlation_id
    digest = hashlib.sha256(f"{primary}\n{question}".encode()).hexdigest()
    return f"unattributed:{digest[:32]}"
