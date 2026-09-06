"""Offline adapter compatibility with the conversation service's stage schemas."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
from fdai.core.conversation.adaptive_models import AdaptiveDraft, AdaptivePlan, AdaptiveReview
from fdai.delivery.azure.llm.adaptive_answer import (
    AdaptiveModelTarget,
    AzureOpenAIAdaptiveModel,
    AzureOpenAIAdaptiveModelConfig,
)
from fdai.delivery.azure.llm.request_target import ModelRequestTarget
from fdai.shared.providers.workload_identity import IdentityToken
from pydantic import BaseModel


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken("test-token", datetime(2099, 1, 1, tzinfo=UTC), audience)


def _target(name: str) -> AdaptiveModelTarget:
    return AdaptiveModelTarget(
        ModelRequestTarget(
            endpoint="https://example.com", deployment=name, api_version="2024-06-01"
        ),
        publisher="example-publisher",
        family=name,
    )


_PLAN = {
    "draft": None,
    "route": "adaptive",
    "social_act": "greeting",
    "context_dependency": "none",
    "action_requested": False,
    "goals": [
        {
            "goal_id": "explanation",
            "kind": "knowledge",
            "question": "Explain deployment safety.",
            "required": True,
        },
        {
            "goal_id": "example",
            "kind": "environment_example",
            "question": "Show a verified deployment example.",
            "required": False,
        },
    ],
}
_DRAFT = {"sections": [{"goal_id": "explanation", "text": "A general safety explanation."}]}
_REVIEW = {
    "safe": True,
    "complete": True,
    "supported_goal_ids": ["explanation"],
    "issues": [],
}


@pytest.mark.parametrize(
    ("stage", "shape", "proposal"),
    [
        ("plan", AdaptivePlan, _PLAN),
        ("answer", AdaptiveDraft, _DRAFT),
        ("review", AdaptiveReview, _REVIEW),
        ("refine", AdaptiveDraft, _DRAFT),
        ("verify", AdaptiveReview, _REVIEW),
    ],
)
async def test_service_schema_round_trips_without_relaxation(
    stage: str, shape: type[BaseModel], proposal: dict[str, object]
) -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = json.loads(request.content)
        assert body["response_format"]["json_schema"]["strict"] is True
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(proposal)},
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = AzureOpenAIAdaptiveModel(
            identity=_Identity(),
            http_client=client,
            config=AzureOpenAIAdaptiveModelConfig(
                primary=_target("primary"),
                reviewer=_target("reviewer"),
                escalation=_target("refiner"),
            ),
        )
        result = await model.complete(
            stage=stage,
            system_prompt="Server-owned policy.",
            payload={"utterance": "Hello. Explain deployment safety with an optional example."},
            schema=shape.model_json_schema(),
            escalated=stage == "refine",
        )
    assert len(calls) == 1
    assert result is not None
    assert shape.model_validate(result.proposal).model_dump(mode="json") == proposal
