"""Azure OpenAI question generation and review adapter tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from fdai.core.conversation.question_campaign_runner import QuestionGenerationInput
from fdai.core.conversation.question_candidates import NaturalLanguageQuestionCandidate
from fdai.core.conversation.question_perspectives import (
    QuestionAnchorKind,
    QuestionCapabilityFamily,
    QuestionEvidencePosture,
    QuestionExpectedPosture,
    QuestionPerspective,
)
from fdai.core.conversation.question_universe import GeneratedQuestionCase, QuestionCaseClass
from fdai.delivery.azure.llm.question_generation import (
    AzureOpenAIQuestionCandidateReviewer,
    AzureOpenAIQuestionGenerator,
    AzureOpenAIQuestionModelConfig,
)
from fdai.delivery.azure.llm.request_target import ModelRequestTarget

DIGEST = "sha256:" + "a" * 64


class _Identity:
    async def get_token(self, audience: str):
        assert audience == "https://example.com/.default"
        return SimpleNamespace(token="not-a-real-token")


class _Similarity:
    async def maximum_similarity(self, question: str, prior_questions: tuple[str, ...]) -> float:
        assert question
        assert len(prior_questions) <= 100
        return 0.2


def _case() -> GeneratedQuestionCase:
    return GeneratedQuestionCase(
        case_id="q:1",
        principal_manifest_digest=DIGEST,
        declaration_id="object:Resource",
        declaration_digest=DIGEST,
        locale="en",
        case_class=QuestionCaseClass.POSITIVE,
        perspective=QuestionPerspective.RESOURCE,
        required_capability=QuestionCapabilityFamily.OBJECT_SET,
        evidence_posture=QuestionEvidencePosture.FRESH,
        anchor_kind=QuestionAnchorKind.SELECTED_OBJECT,
        expected_posture=QuestionExpectedPosture.ANSWER,
        action_posture="advise_only",
        path_depth=1,
        result_bound=20,
    )


def _config(family: str) -> AzureOpenAIQuestionModelConfig:
    return AzureOpenAIQuestionModelConfig(
        target=ModelRequestTarget(
            endpoint="https://example.com",
            deployment="example-model",
            api_version="2024-06-01",
            auth_audience="https://example.com/.default",
            binding_id=f"binding-{family}",
        ),
        model_family=family,
        system_prompt="Return strict JSON only.",
        prompt_microusd_per_million=1_000_000,
        completion_microusd_per_million=2_000_000,
    )


async def test_generator_sends_only_bounded_descriptor_and_case() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        content = {
            "question": "What is the current state of the selected resource?",
        }
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(content)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await AzureOpenAIQuestionGenerator(
            identity=_Identity(),
            http_client=client,
            config=_config("family-a"),
        ).generate(
            case=_case(),
            descriptor=QuestionGenerationInput(
                case_id="q:1",
                declaration_kind="object",
                declaration_name="Resource",
                public_description="A provider-neutral managed resource.",
                readable_property_names=("id",),
                link_semantics=(),
                available_capabilities=("object_set",),
            ),
            attempt_number=1,
            prior_fingerprints=(DIGEST,),
        )

    assert result.payload == {"question": "What is the current state of the selected resource?"}
    assert result.usage.prompt_tokens == 10
    assert result.usage.completion_tokens == 5
    assert result.usage.cost_microusd == 20
    serialized = json.dumps(captured)
    messages = captured["messages"]
    assert isinstance(messages, list)
    user_message = messages[1]
    assert isinstance(user_message, dict)
    request_payload = user_message["content"]
    assert isinstance(request_payload, str)
    assert '"response_schema":{"question":"string"}' in request_payload
    assert '"entity_state":"not_applicable"' in request_payload
    assert '"presentation_shape":"default"' in request_payload
    assert "subscription" not in serialized.casefold()
    assert "not-a-real-token" not in serialized


async def test_reviewer_joins_independent_similarity_without_hidden_reasoning() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        content = {
            "equivalent": True,
            "same_locale": True,
            "same_result_shape": True,
            "same_scope": True,
            "same_evidence_authority": True,
            "confidence": 0.95,
        }
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(content)}}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 4},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        review = await AzureOpenAIQuestionCandidateReviewer(
            identity=_Identity(),
            http_client=client,
            config=_config("family-b"),
            similarity=_Similarity(),
        ).review(
            candidate=NaturalLanguageQuestionCandidate(
                schema_version="1.0.0",
                case_id="q:1",
                perspective="resource",
                locale="en",
                question="What is the current state of the selected resource?",
                required_capabilities=("object_set",),
                allowed_dispositions=("answered",),
                anchor_kind="selected_object",
                action_posture="advise_only",
                rule_state="not_applicable",
            ),
            expected_case=_case(),
            prior_questions=(),
        )

    assert review.reviewer_family == "family-b"
    assert review.max_embedding_similarity == 0.2
    assert review.confidence == 0.95
    assert review.usage.prompt_tokens == 8
    assert review.usage.completion_tokens == 4
    assert review.usage.cost_microusd == 16
    messages = captured["messages"]
    assert isinstance(messages, list)
    user_message = messages[1]
    assert isinstance(user_message, dict)
    request_payload = user_message["content"]
    assert isinstance(request_payload, str)
    assert '"entity_state":"not_applicable"' in request_payload
    assert '"temporal_state":"not_applicable"' in request_payload
    assert '"causal_result":"not_applicable"' in request_payload
    assert '"presentation_shape":"default"' in request_payload


async def test_provider_failure_does_not_chain_sensitive_exception_content() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise RuntimeError("Bearer sensitive-provider-content")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        generator = AzureOpenAIQuestionGenerator(
            identity=_Identity(),
            http_client=client,
            config=_config("family-a"),
        )
        with pytest.raises(
            RuntimeError,
            match="question model request failed: RuntimeError",
        ) as caught:
            await generator.generate(
                case=_case(),
                descriptor=QuestionGenerationInput(
                    case_id="q:1",
                    declaration_kind="object",
                    declaration_name="Resource",
                    public_description="A provider-neutral managed resource.",
                    readable_property_names=("id",),
                    link_semantics=(),
                    available_capabilities=("object_set",),
                ),
                attempt_number=1,
                prior_fingerprints=(),
            )

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "sensitive-provider-content" not in str(caught.value)
