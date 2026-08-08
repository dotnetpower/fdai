from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fdai.core.conversation_assurance import AssuranceCriterion, TurnAssessmentInput
from fdai.core.metering import InMemoryMeteringSink, MeteringEmitter
from fdai.core.metering.pricing import PricingTable
from fdai.delivery.azure.llm.conversation_assurance import (
    AzureConversationAssuranceEvaluator,
    AzureConversationAssuranceEvaluatorConfig,
)
from fdai.shared.providers.workload_identity import IdentityToken, WorkloadIdentity


class _Identity(WorkloadIdentity):
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="test-token",  # noqa: S106 - test-only token
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=5),
            audience=audience,
        )


def _turn() -> TurnAssessmentInput:
    return TurnAssessmentInput(
        turn_id="turn-1",
        conversation_id="conversation-1",
        principal_scope="principal-1",
        question="What changed?",
        answer="One verified resource changed.",
        question_digest="q" * 64,
        answer_digest="a" * 64,
        evidence_manifest_digest="e" * 64,
        evidence_refs=("evidence:1",),
        verification_status="verified",
        verification_authority="server_inventory_graph",
        checks_completed=1,
        checks_total=1,
        reference_facts=("Exactly one verified resource changed.",),
    )


def _response_payload(*, criterion: str = "factual_correctness", score: object = 4) -> str:
    return json.dumps(
        {
            "scores": [
                {
                    "criterion": criterion,
                    "score": score,
                    "rationale": "Supported by evidence.",
                    "evidence_refs": ["evidence:1"],
                }
            ]
        }
    )


def _transport(content: str, captured: list[httpx.Request]) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
            },
        )

    return httpx.MockTransport(handler)


def _config() -> AzureConversationAssuranceEvaluatorConfig:
    return AzureConversationAssuranceEvaluatorConfig(
        endpoint="https://example.com",
        deployment="assurance-model",
        model_identity="publisher:model",
        model_family="family-a",
        system_prompt="Evaluate the bounded turn.",
    )


def _pricing() -> PricingTable:
    return PricingTable.from_mapping(
        {
            "family-a": {
                "input_per_1k": Decimal("0.001"),
                "output_per_1k": Decimal("0.002"),
            }
        }
    )


async def test_evaluator_parses_scores_and_usage() -> None:
    captured: list[httpx.Request] = []
    sink = InMemoryMeteringSink()
    async with httpx.AsyncClient(transport=_transport(_response_payload(), captured)) as client:
        evaluator = AzureConversationAssuranceEvaluator(
            identity=_Identity(),
            http_client=client,
            config=_config(),
            metering=MeteringEmitter(
                sink=sink,
                capability_id="conversation.assurance",
                model_key="family-a",
                tier="T2",
                pricing=_pricing(),
            ),
            pricing=_pricing(),
        )

        output = await evaluator.evaluate(_turn())

    assert output.scores[0].criterion is AssuranceCriterion.FACTUAL_CORRECTNESS
    assert output.prompt_tokens == 7
    assert output.completion_tokens == 3
    assert output.cost_microusd == 13
    assert evaluator.prospective_cost_microusd > 0
    (invocation,) = await sink.invocations()
    assert invocation.cost == Decimal("0.000013")
    sent = json.loads(captured[0].content)
    prompt = json.loads(sent["messages"][1]["content"])
    assert prompt["allowed_evidence_refs"] == ["evidence:1"]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (_response_payload(criterion="invented"), "criterion is unsupported"),
        (_response_payload(score=3.5), "score MUST be an integer"),
        (_response_payload(score=5), "score MUST be in"),
        ("not-json", "non-JSON"),
    ],
)
async def test_evaluator_rejects_malformed_output(content: str, message: str) -> None:
    async with httpx.AsyncClient(transport=_transport(content, [])) as client:
        evaluator = AzureConversationAssuranceEvaluator(
            identity=_Identity(),
            http_client=client,
            config=_config(),
        )

        with pytest.raises(RuntimeError, match=message):
            await evaluator.evaluate(_turn())
