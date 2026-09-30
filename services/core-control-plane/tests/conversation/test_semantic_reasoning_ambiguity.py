"""A third model family decides only whether a clarified question has one plausible reading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fdai.core.conversation.semantic_reasoning_ambiguity import (
    ambiguity_schema,
    ambiguity_verdict,
)
from fdai.core.prompts.profiles import compose_static_selection
from fdai.core.prompts.registry import FileSystemPromptRegistry
from fdai.delivery.azure.llm.request_target import ModelRequestTarget
from fdai.delivery.azure.llm.semantic_question_form import (
    AzureOpenAIQuestionFormConfig,
    AzureOpenAIQuestionFormModel,
)

from tests.conversation.test_semantic_reasoning_shadow import _Identity

_ROOT = Path(__file__).resolve().parents[4]


def _target(deployment: str) -> ModelRequestTarget:
    return ModelRequestTarget(
        endpoint="https://example.com",
        deployment=deployment,
        api_version="2024-06-01",
        auth_audience="https://example.com/.default",
        binding_id=f"binding-{deployment}",
    )


@pytest.mark.parametrize(
    ("answer", "verdict"),
    (
        ({"readings": "one"}, "one"),
        ({"readings": "several"}, "several"),
        ({"readings": "unclear"}, "unclear"),
        ({"readings": "both"}, "invalid"),
        ({}, "invalid"),
        (None, "unavailable"),
    ),
)
def test_only_the_closed_readings_are_verdicts(answer: Any, verdict: str) -> None:
    assert ambiguity_verdict(answer) == verdict
    assert ambiguity_schema()["properties"]["readings"]["enum"] == ["one", "several", "unclear"]


async def test_the_third_family_reads_only_the_masked_question() -> None:
    identifier = (
        "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-app/providers/"
        "Microsoft.KeyVault/vaults/kv-app"
    )
    utterance = f"Why did {identifier} change?"
    sent: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append((str(request.url), json.loads(request.content)))
        content = {"readings": "one"}
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(content)}}]}
        )

    def adapter(third: str | None) -> AzureOpenAIQuestionFormModel:
        return AzureOpenAIQuestionFormModel(
            identity=_Identity(),  # type: ignore[arg-type]
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            config=AzureOpenAIQuestionFormConfig(
                candidates=(_target("form-model"),),
                form_system_prompt="Return the closed question form.",
                concept_system_prompt="Choose concepts.",
                extraction_candidates=(_target("review-model"),),
                ambiguity_system_prompt="Decide whether one reading exists." if third else None,
                ambiguity_candidates=(_target(third),) if third else (),
            ),
        )

    answer = await adapter("reasoning-model").check_ambiguity(
        utterance=utterance, context=("an earlier turn",), locale="en"
    )
    unconfigured = await adapter(None).check_ambiguity(utterance=utterance, context=(), locale="en")

    assert answer == {"readings": "one"} and unconfigured is None
    ((url, body),) = sent
    assert "reasoning-model" in url
    payload = json.loads(body["messages"][-1]["content"])
    # Neither reading, nor earlier turns, nor the identifier reaches the reader.
    assert set(payload) == {"utterance", "locale"}
    assert "⟦ID1⟧" in payload["utterance"] and "00000000-0000" not in json.dumps(body)
    assert "an earlier turn" not in json.dumps(body)


def test_the_ambiguity_prompt_composes_within_its_budget() -> None:
    registry = FileSystemPromptRegistry(_ROOT / "rule-catalog")

    composed = compose_static_selection(registry.resolve("semantic.ambiguity_check"))

    assert composed.system_text
