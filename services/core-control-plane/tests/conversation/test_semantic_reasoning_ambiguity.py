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


async def test_the_third_family_is_told_only_that_earlier_results_are_in_hand() -> None:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps({"readings": "one"})}}]}
        )

    model = AzureOpenAIQuestionFormModel(
        identity=_Identity(),  # type: ignore[arg-type]
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        config=AzureOpenAIQuestionFormConfig(
            candidates=(_target("form-model"),),
            form_system_prompt="Return the closed question form.",
            concept_system_prompt="Choose concepts.",
            extraction_candidates=(_target("review-model"),),
            ambiguity_system_prompt="Decide whether one reading exists.",
            ambiguity_candidates=(_target("reasoning-model"),),
        ),
    )

    await model.check_ambiguity(utterance="실행중인것만", context=("list",), locale="ko")
    await model.check_ambiguity(
        utterance="실행중인것만", context=("list",), locale="ko", earlier_results=True
    )

    plain, informed = (json.loads(body["messages"][-1]["content"]) for body in sent)
    assert set(plain) == {"utterance", "locale"}
    # The flag carries no reading and no earlier text, so the reader still cannot side with one.
    assert informed == {**plain, "earlier_results_available": True}
    assert "list" not in json.dumps(sent[1]["messages"][-1])


def test_the_ambiguity_prompt_composes_within_its_budget() -> None:
    registry = FileSystemPromptRegistry(_ROOT / "rule-catalog")

    composed = compose_static_selection(registry.resolve("semantic.ambiguity_check"))

    assert composed.system_text


async def test_a_capability_named_t2_target_is_called_with_its_family_token_field() -> None:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps({"readings": "one"})}}]}
        )

    # A T2 target without an endpoint binding is named after its capability, so only its
    # resolved family says that the model bounds output with completion tokens.
    reasoner = ModelRequestTarget(
        endpoint="https://example.com",
        deployment="t2.reasoner.primary",
        api_version="2024-06-01",
        auth_audience="https://example.com/.default",
        model_family="gpt-5.4",
    )
    model = AzureOpenAIQuestionFormModel(
        identity=_Identity(),  # type: ignore[arg-type]
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        config=AzureOpenAIQuestionFormConfig(
            candidates=(_target("form-model"),),
            form_system_prompt="Return the closed question form.",
            concept_system_prompt="Choose concepts.",
            extraction_candidates=(_target("review-model"),),
            ambiguity_system_prompt="Decide whether one reading exists.",
            ambiguity_candidates=(reasoner,),
        ),
    )

    assert await model.check_ambiguity(utterance="Why?", context=(), locale="en") == {
        "readings": "one"
    }
    ((body,),) = [(item,) for item in sent]
    assert "max_completion_tokens" in body
    assert "max_tokens" not in body and "temperature" not in body
