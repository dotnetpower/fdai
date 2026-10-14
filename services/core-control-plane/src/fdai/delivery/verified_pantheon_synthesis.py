"""Model-backed Pantheon composition with deterministic and independent claim checks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

from fdai_service_contracts.answer_claims import ComposedAnswer

from fdai.agents import DeliberationRequest, SynthesisOutcome, SynthesisVerification
from fdai.core.conversation.adaptive_prompt import AdaptiveModel
from fdai.core.conversation.model_observation import ConversationModelResponse
from fdai.core.conversation.semantic_reasoning_claims import (
    GoalEvidence,
    GoalEvidenceStatus,
    verify_answer_claims,
)
from fdai.core.conversation.verified_answer_authoring import EntailmentReason
from fdai.core.metering.budget import BudgetChargingMeteringSink, BudgetLedger, ModelBudget
from fdai.core.metering.pricing import PricingTable
from fdai.core.metering.records import InvocationMode, InvocationScope, LlmInvocation
from fdai.core.metering.sink import MeteringSink
from fdai.core.metering.usage import TokenUsage
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable


@dataclass(frozen=True, slots=True)
class StructuredSynthesisOutcome(SynthesisOutcome):
    authored_answer: ComposedAnswer | None = None


def _evidence(request: DeliberationRequest) -> tuple[GoalEvidence, ...]:
    return tuple(
        GoalEvidence(
            goal_id=f"g{index + 1}",
            status=GoalEvidenceStatus.VERIFIED,
            tables={
                "owned_facts": QueryTable(
                    rows=(
                        QueryRow.from_values(
                            claim.agent,
                            {
                                **json.loads(claim.facts_json),
                                "id": claim.agent,
                            },
                        ),
                    ),
                    complete=True,
                )
            },
            required_limitations=("agent_owned_projection_only",),
        )
        for index, claim in enumerate(request.claims)
    )


def _payload(request: DeliberationRequest) -> dict[str, object]:
    return {
        "question": request.question,
        "locale": request.locale,
        "purpose": request.purpose,
        "request_sha256": request.sha256,
        "authority": "presentation_only",
        "goals": [
            {
                "goal_id": goal.goal_id,
                "evidence_class": "agent_owned_projection",
                "live_authority": False,
                "required_limitations": list(goal.required_limitations),
                "source_refs": list(request.claims[index].evidence_refs),
                "nodes": {
                    node: {
                        "rows": [
                            {"row_id": row.row_id, "values": row.values} for row in table.rows
                        ],
                        "complete": table.complete,
                    }
                    for node, table in goal.tables.items()
                },
            }
            for index, goal in enumerate(_evidence(request))
        ],
    }


def _usage(response: ConversationModelResponse) -> TokenUsage | None:
    values = response.observation.usage
    if values is None:
        return None
    prompt_tokens = values.get("prompt_tokens")
    completion_tokens = values.get("completion_tokens")
    if (
        type(prompt_tokens) is not int
        or prompt_tokens < 0
        or type(completion_tokens) is not int
        or completion_tokens < 0
    ):
        return None
    return TokenUsage(prompt_tokens, completion_tokens)


def _budget_key(request: DeliberationRequest) -> str:
    if request.correlation_id:
        return request.correlation_id
    digest = hashlib.sha256(f"{request.primary_agent}\n{request.question}".encode()).hexdigest()
    return f"unattributed:{digest[:32]}"


@dataclass(frozen=True, slots=True)
class VerifiedPantheonSynthesizer:
    model: AdaptiveModel
    system_prompt: str
    model_identity: str
    model_family: str
    model_key: str
    ledger: BudgetLedger
    pricing: PricingTable
    metering: MeteringSink
    model_calls_per_synthesis: ClassVar[int] = 2

    def __post_init__(self) -> None:
        price = self.pricing.pricing_for(self.model_key)
        if price is None or price.currency != "USD":
            raise ValueError("Pantheon synthesis requires explicit USD model pricing")

    async def synthesize(self, request: DeliberationRequest) -> SynthesisOutcome | None:
        response = await self.model.complete(
            stage="answer",
            system_prompt=self.system_prompt,
            payload=_payload(request),
            schema=ComposedAnswer.model_json_schema(),
        )
        if response is None or (usage := _usage(response)) is None:
            return None
        try:
            answer = ComposedAnswer.model_validate(response.proposal)
        except ValueError:
            price = self.pricing.pricing_for(self.model_key)
            if price is not None:
                await BudgetChargingMeteringSink(self.metering, self.ledger).record(
                    LlmInvocation(
                        occurred_at=datetime.now(UTC),
                        correlation_id=_budget_key(request),
                        capability_id="t2.conversation.synthesis",
                        model_key=self.model_key,
                        tier="T2",
                        mode=InvocationMode.SHADOW,
                        usage=usage,
                        usage_scope=InvocationScope.OPERATOR_CHAT,
                        cost=price.cost_of(usage),
                        currency=price.currency,
                    )
                )
            return None
        return StructuredSynthesisOutcome(
            conclusion=answer.text,
            model_identity=self.model_identity,
            model_family=self.model_family,
            model_key=self.model_key,
            usage=usage,
            authored_answer=answer,
        )


_REVIEW_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["claims"],
    "properties": {
        "claims": {
            "type": "array",
            "minItems": 1,
            "maxItems": 64,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["claim_id", "reason"],
                "properties": {
                    "claim_id": {"type": "string", "pattern": "^c[0-9]{1,2}$"},
                    "reason": {"enum": [None, *(reason.value for reason in EntailmentReason)]},
                },
            },
        }
    },
}


@dataclass(frozen=True, slots=True)
class VerifiedPantheonSynthesisVerifier:
    model: AdaptiveModel
    system_prompt: str
    author_identity: str
    reviewer_identity: str
    reviewer_model_key: str
    ledger: BudgetLedger
    pricing: PricingTable
    metering: MeteringSink
    budget: ModelBudget

    def __post_init__(self) -> None:
        if self.author_identity.strip().casefold() == self.reviewer_identity.strip().casefold():
            raise ValueError("Pantheon answer review MUST use an independent model")
        price = self.pricing.pricing_for(self.reviewer_model_key)
        if price is None or price.currency != "USD":
            raise ValueError("Pantheon review requires explicit USD model pricing")

    async def verify(
        self,
        request: DeliberationRequest,
        outcome: SynthesisOutcome,
    ) -> SynthesisVerification | None:
        if not isinstance(outcome, StructuredSynthesisOutcome) or outcome.authored_answer is None:
            return None
        answer = outcome.authored_answer
        if outcome.model_identity != self.author_identity or answer.text != outcome.conclusion:
            return None
        verdict = verify_answer_claims(
            answer,
            evidence=_evidence(request),
            utterance=request.question,
            known_identities=frozenset(claim.agent for claim in request.claims),
        )
        if not verdict.accepted:
            return self._receipt(request, outcome, False)
        spent = await self.ledger.spend(_budget_key(request))
        ceiling = self.budget.max_cost_microusd_per_correlation
        if ceiling is not None and spent.cost_microusd >= ceiling:
            return None
        response = await self.model.complete(
            stage="verify",
            system_prompt=self.system_prompt,
            payload={**_payload(request), "answer": answer.model_dump(mode="json")},
            schema=_REVIEW_SCHEMA,
        )
        if response is None or (usage := _usage(response)) is None:
            return None
        price = self.pricing.pricing_for(self.reviewer_model_key)
        if price is None:
            return None
        await BudgetChargingMeteringSink(self.metering, self.ledger).record(
            LlmInvocation(
                occurred_at=datetime.now(UTC),
                correlation_id=_budget_key(request),
                capability_id="t2.conversation.review",
                model_key=self.reviewer_model_key,
                tier="T2",
                mode=InvocationMode.SHADOW,
                usage=usage,
                usage_scope=InvocationScope.OPERATOR_CHAT,
                cost=price.cost_of(usage),
                currency=price.currency,
            )
        )
        records = response.proposal.get("claims")
        if set(response.proposal) != {"claims"} or not isinstance(records, list):
            return None
        expected = {claim.id for claim in answer.claims}
        if (
            len(records) != len(expected)
            or any(
                not isinstance(record, dict)
                or set(record) != {"claim_id", "reason"}
                or not isinstance(record.get("claim_id"), str)
                or record.get("claim_id") not in expected
                or not (
                    record.get("reason") is None
                    or isinstance(record.get("reason"), str)
                    and record.get("reason") in {reason.value for reason in EntailmentReason}
                )
                for record in records
            )
            or {record["claim_id"] for record in records} != expected
        ):
            return None
        return self._receipt(request, outcome, all(record["reason"] is None for record in records))

    def _receipt(
        self,
        request: DeliberationRequest,
        outcome: SynthesisOutcome,
        accepted: bool,
    ) -> SynthesisVerification:
        return SynthesisVerification(
            accepted=accepted,
            request_sha256=request.sha256,
            conclusion_sha256=hashlib.sha256(outcome.conclusion.encode()).hexdigest(),
            evidence_refs=tuple(
                sorted({ref for claim in request.claims for ref in claim.evidence_refs})
            ),
            verifier_identity=self.reviewer_identity,
        )
