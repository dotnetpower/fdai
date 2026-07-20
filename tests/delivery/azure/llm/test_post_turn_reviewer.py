from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx

from fdai.core.learning import OperatorMemoryCandidate, PostTurnReviewInput
from fdai.core.operator_memory import MemoryCategory, ScopeKind
from fdai.delivery.azure.llm.post_turn_reviewer import (
    AzureOpenAIPostTurnModel,
    AzureOpenAIPostTurnModelConfig,
)
from fdai.shared.providers.workload_identity import IdentityToken


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        assert audience == "https://cognitiveservices.azure.com/.default"
        return IdentityToken(
            token="test-token",
            expires_at=datetime(2030, 1, 1, tzinfo=UTC),
            audience=audience,
        )


def _input() -> PostTurnReviewInput:
    return PostTurnReviewInput(
        review_id="review-1",
        principal_scope="principal-hash-1",
        operator_turn_id="turn-operator-1",
        assistant_turn_id="turn-assistant-1",
        completed_at=datetime(2026, 7, 20, tzinfo=UTC),
        operator_body="Use the scoped query.",
        assistant_body="The scoped query succeeded.",
        explicit_corrections=("Use the scoped query next time.",),
        evidence_refs=("audit:1",),
        memory_scope_kind=ScopeKind.RESOURCE,
        memory_scope_ref="resource:1",
    )


async def test_posts_strict_json_request_and_parses_typed_candidate() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "kind": "operator_memory",
                                    "scope_kind": "resource",
                                    "scope_ref": "resource:1",
                                    "category": "runbook-hint",
                                    "body": "Use the scoped query before escalation.",
                                    "evidence_refs": ["audit:1"],
                                    "confidence": 0.9,
                                }
                            )
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = AzureOpenAIPostTurnModel(
            identity=_Identity(),
            http_client=client,
            config=AzureOpenAIPostTurnModelConfig(
                endpoint="https://example.openai.azure.com",
                deployment="review-model",
                model_identity="review-model-a",
                model_family="family-a",
                system_prompt="Return one inert proposal as strict JSON.",
            ),
        )
        result = await model.propose(_input())

    assert result == OperatorMemoryCandidate(
        scope_kind=ScopeKind.RESOURCE,
        scope_ref="resource:1",
        category=MemoryCategory.RUNBOOK_HINT,
        body="Use the scoped query before escalation.",
        evidence_refs=("audit:1",),
        confidence=0.9,
    )
    assert captured["temperature"] == 0.0
    assert captured["response_format"] == {"type": "json_object"}
    prompt = captured["messages"][1]["content"]  # type: ignore[index]
    assert '"turn_data_trusted": false' in prompt


async def test_invalid_response_fails_closed() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"choices": []}))
    ) as client:
        model = AzureOpenAIPostTurnModel(
            identity=_Identity(),
            http_client=client,
            config=AzureOpenAIPostTurnModelConfig(
                endpoint="https://example.openai.azure.com",
                deployment="review-model",
                model_identity="review-model-a",
                model_family="family-a",
                system_prompt="Return strict JSON.",
            ),
        )

        try:
            await model.propose(_input())
        except RuntimeError as exc:
            assert "MUST be a JSON object" in str(exc)
        else:
            raise AssertionError("invalid response did not fail closed")
