"""Azure OpenAI adapters for bounded question wording and independent review."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Protocol

import httpx

from fdai.core.conversation.question_campaign_runner import (
    QuestionCandidateGenerator,
    QuestionGenerationInput,
)
from fdai.core.conversation.question_candidates import (
    NaturalLanguageQuestionCandidate,
    QuestionCandidateGeneration,
    QuestionCandidateReview,
    QuestionCandidateReviewer,
    QuestionModelUsage,
)
from fdai.core.conversation.question_universe import GeneratedQuestionCase
from fdai.delivery.azure.llm.completion_body import completion_body_params
from fdai.delivery.azure.llm.request_target import ModelRequestTarget
from fdai.shared.providers.workload_identity import WorkloadIdentity

_MAX_PROMPT_CHARS = 16_384
_MAX_RESPONSE_BYTES = 32_768
_MAX_PRIOR_QUESTIONS = 100


class QuestionEmbeddingSimilarity(Protocol):
    """Return maximum similarity using a separately bound embedding capability."""

    async def maximum_similarity(
        self,
        question: str,
        prior_questions: tuple[str, ...],
    ) -> float: ...


@dataclass(frozen=True, slots=True)
class AzureOpenAIQuestionModelConfig:
    """Exact resolved target and catalog-owned prompt for one question model role."""

    target: ModelRequestTarget
    model_family: str
    system_prompt: str
    timeout_seconds: float = 90.0
    max_tokens: int = 1_024
    max_prompt_tokens: int = 4_096
    prompt_microusd_per_million: int = 0
    completion_microusd_per_million: int = 0

    def __post_init__(self) -> None:
        if not self.model_family:
            raise ValueError("question model family MUST be non-empty")
        if not self.system_prompt or len(self.system_prompt) > _MAX_PROMPT_CHARS:
            raise ValueError("question model system prompt MUST be non-empty and bounded")
        if not 0 < self.timeout_seconds <= 300:
            raise ValueError("question model timeout_seconds MUST be in (0, 300]")
        if not 1 <= self.max_tokens <= 2_048:
            raise ValueError("question model max_tokens MUST be in [1, 2048]")
        if not 1 <= self.max_prompt_tokens <= 16_384:
            raise ValueError("question model max_prompt_tokens MUST be in [1, 16384]")
        if self.prompt_microusd_per_million < 0 or self.completion_microusd_per_million < 0:
            raise ValueError("question model pricing MUST be non-negative")


class AzureOpenAIQuestionGenerator(QuestionCandidateGenerator):
    """Generate one strict JSON candidate with no query or tool execution."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureOpenAIQuestionModelConfig,
    ) -> None:
        self._identity = identity
        self._http = http_client
        self._config = config

    @property
    def model_family(self) -> str:
        return self._config.model_family

    @property
    def max_usage_per_call(self) -> QuestionModelUsage:
        return _max_usage(self._config)

    async def generate(
        self,
        *,
        case: GeneratedQuestionCase,
        descriptor: QuestionGenerationInput,
        attempt_number: int,
        prior_fingerprints: tuple[str, ...],
    ) -> QuestionCandidateGeneration:
        payload = {
            "case": {
                "case_id": case.case_id,
                "perspective": case.perspective.value,
                "locale": case.locale,
                "case_class": case.case_class.value,
                "evidence_posture": case.evidence_posture.value,
                "required_capabilities": [case.required_capability.value],
                "allowed_dispositions": [_allowed_disposition(case)],
                "anchor_kind": case.anchor_kind.value,
                "action_posture": case.action_posture,
                "rule_state": case.rule_state.value,
                "path_depth": case.path_depth,
                "result_bound": case.result_bound,
            },
            "descriptor": asdict(descriptor),
            "attempt_number": attempt_number,
            "prior_fingerprints": list(prior_fingerprints[-_MAX_PRIOR_QUESTIONS:]),
        }
        result, usage = await _complete_json(
            identity=self._identity,
            http_client=self._http,
            config=self._config,
            payload=payload,
        )
        return QuestionCandidateGeneration(payload=result, usage=usage)


class AzureOpenAIQuestionCandidateReviewer(QuestionCandidateReviewer):
    """Review semantic equivalence and join independent embedding similarity."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureOpenAIQuestionModelConfig,
        similarity: QuestionEmbeddingSimilarity,
    ) -> None:
        self._identity = identity
        self._http = http_client
        self._config = config
        self._similarity = similarity

    @property
    def max_usage_per_call(self) -> QuestionModelUsage:
        return _max_usage(self._config)

    async def review(
        self,
        *,
        candidate: NaturalLanguageQuestionCandidate,
        expected_case: GeneratedQuestionCase,
        prior_questions: tuple[str, ...],
    ) -> QuestionCandidateReview:
        if len(prior_questions) > _MAX_PRIOR_QUESTIONS:
            raise ValueError(f"question review prior corpus exceeds {_MAX_PRIOR_QUESTIONS}")
        similarity = await self._similarity.maximum_similarity(
            candidate.question,
            prior_questions,
        )
        if not 0.0 <= similarity <= 1.0:
            raise ValueError("question embedding similarity MUST be in [0, 1]")
        payload = {
            "candidate": asdict(candidate),
            "expected_case": {
                "case_id": expected_case.case_id,
                "perspective": expected_case.perspective.value,
                "locale": expected_case.locale,
                "required_capability": expected_case.required_capability.value,
                "evidence_posture": expected_case.evidence_posture.value,
                "anchor_kind": expected_case.anchor_kind.value,
                "expected_posture": expected_case.expected_posture.value,
                "action_posture": expected_case.action_posture,
                "rule_state": expected_case.rule_state.value,
            },
        }
        result, usage = await _complete_json(
            identity=self._identity,
            http_client=self._http,
            config=self._config,
            payload=payload,
        )
        expected = {
            "equivalent",
            "same_locale",
            "same_result_shape",
            "same_scope",
            "same_evidence_authority",
            "confidence",
        }
        if set(result) != expected:
            raise RuntimeError("question review response schema is invalid")
        flags = tuple(
            result[name]
            for name in (
                "equivalent",
                "same_locale",
                "same_result_shape",
                "same_scope",
                "same_evidence_authority",
            )
        )
        if any(type(value) is not bool for value in flags):
            raise RuntimeError("question review flags MUST be boolean")
        confidence = result["confidence"]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise RuntimeError("question review confidence MUST be numeric")
        return QuestionCandidateReview(
            reviewer_identity=self._config.target.binding_id or self._config.target.deployment,
            reviewer_family=self._config.model_family,
            equivalent=bool(result["equivalent"]),
            same_locale=bool(result["same_locale"]),
            same_result_shape=bool(result["same_result_shape"]),
            same_scope=bool(result["same_scope"]),
            same_evidence_authority=bool(result["same_evidence_authority"]),
            confidence=float(confidence),
            max_embedding_similarity=similarity,
            usage=usage,
        )


async def _complete_json(
    *,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    config: AzureOpenAIQuestionModelConfig,
    payload: Mapping[str, object],
) -> tuple[dict[str, object], QuestionModelUsage]:
    request = config.target.operation("chat/completions")
    token = await identity.get_token(config.target.auth_audience)
    body: dict[str, Any] = {
        "messages": [
            {"role": "system", "content": config.system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {"untrusted_input": payload},
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            },
        ],
        "response_format": {"type": "json_object"},
        **completion_body_params(
            config.target.deployment,
            temperature=0.0,
            max_tokens=config.max_tokens,
        ),
    }
    if request.model_body_field is not None:
        body["model"] = request.model_body_field
    failure_kind: str | None = None
    result: object = None
    prompt_tokens = 0
    completion_tokens = 0
    try:
        response = await http_client.post(
            request.url,
            params=request.params,
            headers={
                "Authorization": f"Bearer {token.token}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=config.timeout_seconds,
        )
        response.raise_for_status()
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise RuntimeError("question model response exceeds its byte bound")
        envelope = response.json()
        choices = envelope.get("choices") if isinstance(envelope, Mapping) else None
        raw_usage = envelope.get("usage") if isinstance(envelope, Mapping) else None
        message = choices[0].get("message") if isinstance(choices, list) and choices else None
        content = message.get("content") if isinstance(message, Mapping) else None
        result = json.loads(content) if isinstance(content, str) else None
        if not isinstance(raw_usage, Mapping):
            raise RuntimeError("question model response omitted usage")
        prompt_tokens = _usage_integer(raw_usage, "prompt_tokens")
        completion_tokens = _usage_integer(raw_usage, "completion_tokens")
    except Exception as error:  # noqa: BLE001 - provider content never enters the error
        failure_kind = type(error).__name__
    if failure_kind is not None:
        raise RuntimeError(f"question model request failed: {failure_kind}")
    if not isinstance(result, dict):
        raise RuntimeError("question model response MUST be a JSON object")
    cost_microusd = math.ceil(
        (
            prompt_tokens * config.prompt_microusd_per_million
            + completion_tokens * config.completion_microusd_per_million
        )
        / 1_000_000
    )
    return (
        {str(key): value for key, value in result.items()},
        QuestionModelUsage(
            model_calls=1,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_microusd=cost_microusd,
        ),
    )


def _usage_integer(usage: Mapping[object, object], key: str) -> int:
    value = usage.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError("question model response usage is invalid")
    return value


def _max_usage(config: AzureOpenAIQuestionModelConfig) -> QuestionModelUsage:
    return QuestionModelUsage(
        model_calls=1,
        prompt_tokens=config.max_prompt_tokens,
        completion_tokens=config.max_tokens,
        cost_microusd=math.ceil(
            (
                config.max_prompt_tokens * config.prompt_microusd_per_million
                + config.max_tokens * config.completion_microusd_per_million
            )
            / 1_000_000
        ),
    )


def _allowed_disposition(case: GeneratedQuestionCase) -> str:
    return {
        "answer": "answered",
        "clarify": "clarification",
        "hold": "held",
        "unsupported": "unsupported",
        "action_draft": "action_draft",
    }[case.expected_posture.value]


__all__ = [
    "AzureOpenAIQuestionCandidateReviewer",
    "AzureOpenAIQuestionGenerator",
    "AzureOpenAIQuestionModelConfig",
    "QuestionEmbeddingSimilarity",
]
