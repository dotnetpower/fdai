"""Azure OpenAI adapter for candidate-only semantic judgment."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

from fdai.core.conversation.semantic_judgment import (
    SemanticJudgmentModelResponse,
    SemanticJudgmentObservation,
)
from fdai.delivery.azure.llm.completion_body import completion_body_params
from fdai.delivery.azure.llm.model_trace import (
    bounded_usage,
    complete_model_trace,
    start_model_trace,
)
from fdai.delivery.azure.llm.request_target import ModelRequestTarget
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger(__name__)
_MAX_CANDIDATES = 8
_MAX_PROMPT_CHARS = 32_768
_MAX_REQUEST_BYTES = 786_432
_MAX_RESPONSE_BYTES = 65_536


@dataclass(frozen=True, slots=True)
class AzureOpenAISemanticJudgmentModelConfig:
    """Bound semantic-judgment targets and catalog-owned instruction text."""

    candidates: tuple[ModelRequestTarget, ...]
    system_prompt: str
    timeout_seconds: float = 30.0
    max_tokens: int = 2_048

    def __post_init__(self) -> None:
        if not 1 <= len(self.candidates) <= _MAX_CANDIDATES:
            raise ValueError(f"semantic judgment candidates MUST contain 1 to {_MAX_CANDIDATES}")
        identities = tuple(
            (candidate.endpoint, candidate.deployment, candidate.api_version)
            for candidate in self.candidates
        )
        if len(identities) != len(set(identities)):
            raise ValueError("semantic judgment candidates MUST be unique")
        if not self.system_prompt or len(self.system_prompt) > _MAX_PROMPT_CHARS:
            raise ValueError("semantic judgment system prompt MUST be non-empty and bounded")
        if not 0 < self.timeout_seconds <= 120:
            raise ValueError("semantic judgment timeout_seconds MUST be in (0, 120]")
        if not 1 <= self.max_tokens <= 4_096:
            raise ValueError("semantic judgment max_tokens MUST be in [1, 4096]")


class AzureOpenAISemanticJudgmentModel:
    """Return one bounded JSON proposal without granting action authority.

    Calls run outside the owning event loop. Provider and identity I/O is scheduled
    back onto that loop, and all-candidate transport failure returns ``None``.
    Invalid JSON returns a deliberately invalid mapping so the shared boundary can
    record ``malformed`` and decide whether to escalate to T2.
    """

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureOpenAISemanticJudgmentModelConfig,
        owner_loop: asyncio.AbstractEventLoop,
    ) -> None:
        if not owner_loop.is_running():
            raise ValueError("semantic judgment owner_loop MUST be running")
        self._identity = identity
        self._http = http_client
        self._config = config
        self._owner_loop = owner_loop

    def judge(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        capabilities: tuple[dict[str, Any], ...],
        profile_id: str,
        profile_version: str,
        schema_repair: tuple[dict[str, str], ...],
    ) -> Mapping[str, Any] | SemanticJudgmentModelResponse | None:
        """Return a raw JSON-object proposal or ``None`` on transport failure."""

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is self._owner_loop:
            _LOGGER.error("semantic_judgment_owner_loop_call_rejected")
            return None
        input_digest = content_digest({"utterance": utterance})
        payload = {
            "utterance": utterance,
            "context": context,
            "capabilities": capabilities,
            "profile_id": profile_id,
            "profile_version": profile_version,
            "schema_repair": schema_repair,
        }
        try:
            encoded = json.dumps(
                {"untrusted_input": payload},
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError):
            return {"invalid_semantic_judgment_input": True}
        if len(encoded.encode()) > _MAX_REQUEST_BYTES:
            return {"invalid_semantic_judgment_input": True}
        future = asyncio.run_coroutine_threadsafe(
            self._complete(encoded, input_digest=input_digest),
            self._owner_loop,
        )
        try:
            return future.result(timeout=self._config.timeout_seconds + 1)
        except Exception as exc:  # noqa: BLE001 - adapter contains provider details
            future.cancel()
            _LOGGER.warning(
                "semantic_judgment_model_unavailable",
                extra={"failure_type": type(exc).__name__, "input_digest": input_digest},
            )
            return None

    async def _complete(
        self,
        user_content: str,
        *,
        input_digest: str,
    ) -> SemanticJudgmentModelResponse | None:
        schema = json.dumps(
            SemanticJudgmentProposal.model_json_schema(),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        system_content = f"{self._config.system_prompt}\nRequired JSON Schema:\n{schema}"
        candidate_timeout = self._config.timeout_seconds / len(self._config.candidates)
        for index, target in enumerate(self._config.candidates):
            try:
                async with asyncio.timeout(candidate_timeout):
                    token = await self._identity.get_token(target.auth_audience)
                    request = target.operation("chat/completions")
                    body: dict[str, Any] = {
                        "messages": [
                            {"role": "system", "content": system_content},
                            {"role": "user", "content": user_content},
                        ],
                        "response_format": {"type": "json_object"},
                        **completion_body_params(
                            target.deployment,
                            temperature=0.0,
                            max_tokens=self._config.max_tokens,
                        ),
                    }
                    if request.model_body_field is not None:
                        body["model"] = request.model_body_field
                    messages = body["messages"]
                    if not isinstance(messages, list):  # pragma: no cover - local construction
                        raise TypeError("semantic judgment messages MUST be a list")
                    trace_start = start_model_trace(messages)
                    response = await self._http.post(
                        request.url,
                        params=request.params,
                        headers={
                            "Authorization": f"Bearer {token.token}",
                            "Content-Type": "application/json",
                        },
                        json=body,
                        timeout=candidate_timeout,
                    )
                    response.raise_for_status()
                    proposal, response_content, usage = _response_mapping(response)
                    trace_call = complete_model_trace(
                        trace_start,
                        call_id=f"semantic-judgment-{index + 1}",
                        kind="semantic-judgment",
                        model=target.deployment,
                        response_content=response_content,
                        usage=usage,
                    )
                    return SemanticJudgmentModelResponse(
                        proposal=proposal,
                        observation=SemanticJudgmentObservation(
                            model=target.deployment,
                            usage=bounded_usage(usage),
                            trace_call=trace_call,
                        ),
                    )
            except Exception as exc:  # noqa: BLE001 - bounded candidate failover
                failure: dict[str, Any] = {
                    "candidate_index": index,
                    "failure_type": type(exc).__name__,
                    "input_digest": input_digest,
                }
                if isinstance(exc, httpx.HTTPStatusError):
                    failure["status_code"] = exc.response.status_code
                _LOGGER.warning("semantic_judgment_candidate_failed", extra=failure)
        return None


def _response_mapping(
    response: httpx.Response,
) -> tuple[Mapping[str, Any], str, Mapping[str, Any] | None]:
    envelope = response.json()
    choices = envelope.get("choices") if isinstance(envelope, Mapping) else None
    usage = envelope.get("usage") if isinstance(envelope, Mapping) else None
    bounded_provider_usage = usage if isinstance(usage, Mapping) else None
    if not isinstance(choices, list) or not choices:
        invalid = "[INVALID_SEMANTIC_JUDGMENT_RESPONSE]"
        return {"invalid_semantic_judgment_response": True}, invalid, bounded_provider_usage
    message = choices[0].get("message") if isinstance(choices[0], Mapping) else None
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, str) or not content or len(content.encode()) > _MAX_RESPONSE_BYTES:
        invalid = "[INVALID_SEMANTIC_JUDGMENT_RESPONSE]"
        return {"invalid_semantic_judgment_response": True}, invalid, bounded_provider_usage
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return {"invalid_semantic_judgment_response": True}, content, bounded_provider_usage
    proposal = (
        payload if isinstance(payload, Mapping) else {"invalid_semantic_judgment_response": True}
    )
    return proposal, content, bounded_provider_usage


__all__ = [
    "AzureOpenAISemanticJudgmentModel",
    "AzureOpenAISemanticJudgmentModelConfig",
]
