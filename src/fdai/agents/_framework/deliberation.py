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
    ) -> None:
        if not specs:
            raise ValueError("conversation deliberator requires agent specs")
        self._specs = {spec.name: spec for spec in specs}
        self._semantic_router = semantic_router
        self._t2_synthesizer = t2_synthesizer
        self._call_responder = call_responder

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
            },
        )
        return _claim(agent_name, response)

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
