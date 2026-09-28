"""Azure OpenAI adapter for the shadow question-form and concept-selection calls.

Both calls return one strict JSON object and never carry authority. The question
form quotes utterance text instead of counting characters, and concept selection
sees one complete catalog shard per call. Transport failure returns ``None`` so
the shadow runner records ``model_unavailable`` instead of guessing.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any

import httpx

from fdai.core.conversation.adaptive_call_scope import call_scoped_provider, run_scoped_model
from fdai.core.conversation.semantic_reasoning_concepts import MAX_SHARD_CHOICES, ConceptShard
from fdai.core.conversation.semantic_reasoning_proposal import question_form_proposal_schema
from fdai.core.prompts import PromptReplayManifest
from fdai.delivery.azure.llm.completion_body import completion_body_params
from fdai.delivery.azure.llm.request_target import ModelRequestTarget
from fdai.delivery.azure.llm.semantic_judgment import _strict_response_format
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger(__name__)
_MAX_CANDIDATES = 8
_MAX_PROMPT_CHARS = 32_768
_MAX_RESPONSE_BYTES = 65_536
_MAX_CONTEXT_ITEMS = 8
_CONCEPT_CHOICE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["shard_digest", "choices"],
    "properties": {
        "shard_digest": {"type": "string"},
        "choices": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["mention", "candidate_ids"],
                "properties": {
                    "mention": {"type": "string"},
                    "candidate_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": MAX_SHARD_CHOICES,
                    },
                },
            },
        },
    },
}


@dataclass(frozen=True, slots=True)
class AzureOpenAIQuestionFormConfig:
    candidates: tuple[ModelRequestTarget, ...]
    form_system_prompt: str
    concept_system_prompt: str
    form_prompt_manifest: PromptReplayManifest | None = None
    concept_prompt_manifest: PromptReplayManifest | None = None
    timeout_seconds: float = 30.0
    form_max_tokens: int = 2_048
    concept_max_tokens: int = 512

    def __post_init__(self) -> None:
        if not 1 <= len(self.candidates) <= _MAX_CANDIDATES:
            raise ValueError(f"question form candidates MUST contain 1 to {_MAX_CANDIDATES}")
        for prompt, manifest in (
            (self.form_system_prompt, self.form_prompt_manifest),
            (self.concept_system_prompt, self.concept_prompt_manifest),
        ):
            if not prompt or len(prompt) > _MAX_PROMPT_CHARS:
                raise ValueError("question form prompts MUST be non-empty and bounded")
            if manifest is not None and (
                manifest.system_text_sha256 != hashlib.sha256(prompt.encode()).hexdigest()
            ):
                raise ValueError("question form prompt manifest does not match its prompt")
        if not 0 < self.timeout_seconds <= 120:
            raise ValueError("question form timeout_seconds MUST be in (0, 120]")
        if not 1 <= self.form_max_tokens <= 4_096 or not 1 <= self.concept_max_tokens <= 2_048:
            raise ValueError("question form output token bounds are out of range")


class AzureOpenAIQuestionFormModel:
    """Implement the shadow ``QuestionFormModel`` port over Azure OpenAI."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureOpenAIQuestionFormConfig,
    ) -> None:
        self._identity = identity
        self._http = http_client
        self._config = config
        self._form_schema = question_form_proposal_schema()

    async def propose_form(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        locale: str,
        pass_index: int,
        prior_goals: tuple[dict[str, Any], ...],
    ) -> Mapping[str, Any] | None:
        payload = {
            "utterance": utterance,
            "context": list(context[-_MAX_CONTEXT_ITEMS:]),
            "locale": locale,
            "pass_index": pass_index,
            "prior_goals": list(prior_goals),
        }
        return await self._complete(
            system_prompt=self._config.form_system_prompt,
            user_payload=payload,
            schema=self._form_schema,
            name="semantic-question-form",
            max_tokens=self._config.form_max_tokens,
        )

    async def choose_concepts(
        self,
        *,
        utterance: str,
        mentions: tuple[dict[str, Any], ...],
        shard: ConceptShard,
    ) -> Mapping[str, Any] | None:
        payload = {
            "utterance": utterance,
            "mentions": list(mentions),
            "shard_digest": shard.digest,
            "shard": shard.payload(),
        }
        return await self._complete(
            system_prompt=self._config.concept_system_prompt,
            user_payload=payload,
            schema=_CONCEPT_CHOICE_SCHEMA,
            name="semantic-concept-selection",
            max_tokens=self._config.concept_max_tokens,
        )

    async def _complete(
        self,
        *,
        system_prompt: str,
        user_payload: Mapping[str, Any],
        schema: Mapping[str, Any],
        name: str,
        max_tokens: int,
    ) -> Mapping[str, Any] | None:
        async def attempt() -> Mapping[str, Any] | None:
            return await self._attempt(
                system_prompt=system_prompt,
                user_content=json.dumps(user_payload, ensure_ascii=False, sort_keys=True),
                response_format=_strict_response_format(schema, name=name),
                name=name,
                max_tokens=max_tokens,
            )

        return await run_scoped_model(attempt)

    async def _attempt(
        self,
        *,
        system_prompt: str,
        user_content: str,
        response_format: Mapping[str, Any],
        name: str,
        max_tokens: int,
    ) -> Mapping[str, Any] | None:
        candidate_timeout = self._config.timeout_seconds / len(self._config.candidates)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        for index, target in enumerate(self._config.candidates):
            try:
                async with asyncio.timeout(candidate_timeout):
                    token = await self._identity.get_token(target.auth_audience)
                    request = target.operation("chat/completions")
                    body: dict[str, Any] = {
                        "messages": messages,
                        "response_format": dict(response_format),
                        **completion_body_params(
                            target.deployment, temperature=0.0, max_tokens=max_tokens
                        ),
                    }
                    if request.model_body_field is not None:
                        body["model"] = request.model_body_field
                    response, _reservation = await call_scoped_provider(
                        partial(
                            self._http.post,
                            request.url,
                            params=request.params,
                            headers={
                                "Authorization": f"Bearer {token.token}",
                                "Content-Type": "application/json",
                            },
                            json=body,
                            timeout=candidate_timeout,
                        ),
                        request=body,
                        output_tokens=max_tokens,
                    )
                    response.raise_for_status()
                    return _content_object(response)
            except Exception as exc:  # noqa: BLE001 - bounded candidate failover
                failure: dict[str, Any] = {
                    "call_kind": name,
                    "candidate_index": index,
                    "failure_type": type(exc).__name__,
                }
                if isinstance(exc, httpx.HTTPStatusError):
                    failure["status_code"] = exc.response.status_code
                _LOGGER.warning("question_form_candidate_failed", extra=failure)
        return None


def _content_object(response: httpx.Response) -> Mapping[str, Any] | None:
    envelope = response.json()
    choices = envelope.get("choices") if isinstance(envelope, Mapping) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        return None
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, str) or len(content.encode()) > _MAX_RESPONSE_BYTES:
        return None
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, Mapping) else None


__all__ = ["AzureOpenAIQuestionFormConfig", "AzureOpenAIQuestionFormModel"]
