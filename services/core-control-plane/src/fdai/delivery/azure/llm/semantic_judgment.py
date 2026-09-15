"""Azure OpenAI adapter for candidate-only semantic judgment."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Mapping
from concurrent.futures import CancelledError as FutureCancelledError
from dataclasses import dataclass, field
from functools import partial
from typing import Any

import httpx
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.semantic_judgment import (
    SemanticDirectResponseDraft,
    SemanticJudgmentProposal,
)

from fdai.core.conversation.adaptive_call_scope import (
    call_scoped_provider,
    run_scoped_model,
    stop_scoped_provider_retry,
)
from fdai.core.conversation.conversation_preflight import ConversationPreflightProposal
from fdai.core.conversation.semantic_judgment import (
    SemanticJudgmentModelResponse,
    SemanticJudgmentObservation,
)
from fdai.core.prompts import PromptReplayManifest, estimate_chat_request_tokens
from fdai.core.prompts.types import PromptLayer
from fdai.delivery.azure.llm.completion_body import completion_body_params
from fdai.delivery.azure.llm.model_trace import (
    bounded_usage,
    complete_model_trace,
    prepare_model_messages,
    start_model_trace,
)
from fdai.delivery.azure.llm.request_target import ModelRequestTarget
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger(__name__)
_MAX_CANDIDATES = 8
_MAX_PROMPT_CHARS = 32_768
_MAX_REQUEST_BYTES = 786_432
_MAX_RESPONSE_BYTES = 65_536
_MAX_PREFLIGHT_TOKENS = 768
_UNSUPPORTED_STRICT_SCHEMA_KEYS = frozenset(
    {"default", "title", "minLength", "maxLength", "minItems", "maxItems"}
)


@dataclass(frozen=True, slots=True)
class AzureOpenAISemanticJudgmentModelConfig:
    """Bound semantic-judgment targets and catalog-owned instruction text."""

    candidates: tuple[ModelRequestTarget, ...]
    system_prompt: str
    system_prompt_manifest: PromptReplayManifest | None = None
    preflight_system_prompt: str | None = None
    preflight_prompt_manifest: PromptReplayManifest | None = None
    social_narrator_system_prompts: Mapping[str, str] = field(default_factory=dict)
    social_narrator_prompt_manifests: Mapping[str, PromptReplayManifest] = field(
        default_factory=dict
    )
    timeout_seconds: float = 30.0
    social_narrator_timeout_seconds: float = 10.0
    max_tokens: int = 2_048
    intent_hardening_enabled: bool = False

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
        if self.preflight_system_prompt is not None and (
            not self.preflight_system_prompt
            or len(self.preflight_system_prompt) > _MAX_PROMPT_CHARS
        ):
            raise ValueError("conversation preflight system prompt MUST be non-empty and bounded")
        if any(
            not prompt or len(prompt) > _MAX_PROMPT_CHARS
            for prompt in self.social_narrator_system_prompts.values()
        ):
            raise ValueError("social narrator system prompt MUST be non-empty and bounded")
        _validate_prompt_manifest(self.system_prompt, self.system_prompt_manifest)
        _validate_prompt_manifest(
            self.preflight_system_prompt,
            self.preflight_prompt_manifest,
        )
        if set(self.social_narrator_prompt_manifests) - set(self.social_narrator_system_prompts):
            raise ValueError("social narrator prompt manifests require matching prompts")
        for social_act, manifest in self.social_narrator_prompt_manifests.items():
            _validate_prompt_manifest(
                self.social_narrator_system_prompts[social_act],
                manifest,
            )
        if not 0 < self.timeout_seconds <= 120:
            raise ValueError("semantic judgment timeout_seconds MUST be in (0, 120]")
        if not 0 < self.social_narrator_timeout_seconds <= 30:
            raise ValueError("social narrator timeout_seconds MUST be in (0, 30]")
        if not 1 <= self.max_tokens <= 4_096:
            raise ValueError("semantic judgment max_tokens MUST be in [1, 4096]")
        _validate_output_reserve(
            "semantic judgment",
            self.system_prompt_manifest,
            self.max_tokens,
        )
        _validate_output_reserve(
            "conversation preflight",
            self.preflight_prompt_manifest,
            min(self.max_tokens, _MAX_PREFLIGHT_TOKENS),
        )
        for social_act, manifest in self.social_narrator_prompt_manifests.items():
            _validate_output_reserve(f"social narrator {social_act}", manifest, 256)


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
        locale: str,
        direct_response_profile: Mapping[str, Any],
        direct_response_profile_digest: str,
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
            "locale": locale,
            "direct_response_profile": direct_response_profile,
            "direct_response_profile_digest": direct_response_profile_digest,
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
            self._complete(
                encoded,
                input_digest=input_digest,
                proposal_schema=_semantic_judgment_proposal_schema(
                    intent_hardening_enabled=self._config.intent_hardening_enabled,
                    document_query_enabled=_document_query_prompt_enabled(
                        self._config.system_prompt_manifest
                    )
                    and any(
                        capability.get("kind") == "function_type"
                        and capability.get("name") == "query.governed_documents"
                        for capability in capabilities
                    ),
                    source_locale=locale,
                ),
                system_prompt=self._config.system_prompt,
                prompt_manifest=self._config.system_prompt_manifest,
                call_kind="semantic-judgment",
                max_tokens=self._config.max_tokens,
                temperature=0.0,
                timeout_seconds=self._config.timeout_seconds,
            ),
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

    def preflight(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        locale: str,
        direct_response_profile: Mapping[str, Any],
        direct_response_profile_digest: str,
        schema_repair: tuple[dict[str, str], ...],
        cancelled: asyncio.Event | None = None,
    ) -> Mapping[str, Any] | SemanticJudgmentModelResponse | None:
        """Return one compact social/operational route proposal."""

        if self._config.preflight_system_prompt is None:
            return None
        payload = {
            "utterance": utterance,
            "context": context,
            "locale": locale,
            "direct_response_profile": direct_response_profile,
            "direct_response_profile_digest": direct_response_profile_digest,
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
            return None
        if len(encoded.encode()) > _MAX_REQUEST_BYTES:
            return None
        input_digest = content_digest({"utterance": utterance, "locale": locale})
        future = asyncio.run_coroutine_threadsafe(
            self._complete(
                encoded,
                input_digest=input_digest,
                proposal_schema=ConversationPreflightProposal.model_json_schema(),
                system_prompt=self._config.preflight_system_prompt,
                prompt_manifest=self._config.preflight_prompt_manifest,
                call_kind="conversation-preflight",
                max_tokens=min(self._config.max_tokens, _MAX_PREFLIGHT_TOKENS),
                temperature=0.0,
                timeout_seconds=self._config.timeout_seconds,
                allow_candidate_failover=False,
                cancelled=cancelled,
            ),
            self._owner_loop,
        )
        try:
            return future.result(timeout=self._config.timeout_seconds + 1)
        except FutureCancelledError:
            return None
        except Exception as exc:  # noqa: BLE001 - adapter contains provider details
            future.cancel()
            _LOGGER.warning(
                "conversation_preflight_model_unavailable",
                extra={"failure_type": type(exc).__name__, "input_digest": input_digest},
            )
            return None

    def narrate_social(
        self,
        *,
        utterance: str,
        locale: str,
        social_act: str,
        continued: bool,
        direct_response_profile: Mapping[str, Any],
        direct_response_profile_digest: str,
    ) -> Mapping[str, Any] | SemanticJudgmentModelResponse | None:
        """Generate one bounded social response after routing has completed."""

        system_prompt = self._config.social_narrator_system_prompts.get(social_act)
        if system_prompt is None:
            return None
        payload = {
            "utterance": utterance,
            "locale": locale,
            "social_act": social_act,
            "continued": continued,
            "direct_response_profile": direct_response_profile,
            "direct_response_profile_digest": direct_response_profile_digest,
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
            return None
        input_digest = content_digest(
            {"utterance": utterance, "locale": locale, "social_act": social_act}
        )
        future = asyncio.run_coroutine_threadsafe(
            self._complete(
                encoded,
                input_digest=input_digest,
                proposal_schema=SemanticDirectResponseDraft.model_json_schema(),
                system_prompt=system_prompt,
                prompt_manifest=self._config.social_narrator_prompt_manifests.get(social_act),
                call_kind="conversation-social-narrator",
                max_tokens=256,
                temperature=0.3,
                timeout_seconds=self._config.social_narrator_timeout_seconds,
            ),
            self._owner_loop,
        )
        try:
            return future.result(timeout=self._config.social_narrator_timeout_seconds + 1)
        except Exception as exc:  # noqa: BLE001 - adapter contains provider details
            future.cancel()
            _LOGGER.warning(
                "social_response_narrator_unavailable",
                extra={"failure_type": type(exc).__name__, "input_digest": input_digest},
            )
            return None

    async def _complete(
        self,
        user_content: str,
        *,
        input_digest: str,
        proposal_schema: Mapping[str, Any],
        system_prompt: str,
        call_kind: str,
        max_tokens: int,
        temperature: float,
        timeout_seconds: float,
        prompt_manifest: PromptReplayManifest | None = None,
        allow_candidate_failover: bool = True,
        cancelled: asyncio.Event | None = None,
    ) -> SemanticJudgmentModelResponse | None:
        async def complete_attempt() -> SemanticJudgmentModelResponse | None:
            return await self._complete_attempts(
                user_content,
                input_digest=input_digest,
                proposal_schema=proposal_schema,
                system_prompt=system_prompt,
                prompt_manifest=prompt_manifest,
                call_kind=call_kind,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout_seconds=timeout_seconds,
                allow_candidate_failover=allow_candidate_failover,
            )

        async def complete_or_cancel() -> SemanticJudgmentModelResponse | None:
            if cancelled is None:
                return await complete_attempt()
            if cancelled.is_set():
                raise asyncio.CancelledError
            provider_task = asyncio.create_task(complete_attempt())
            cancellation_task = asyncio.create_task(cancelled.wait())
            try:
                done, _pending = await asyncio.wait(
                    (provider_task, cancellation_task),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancellation_task in done and cancelled.is_set():
                    provider_task.cancel()
                    await asyncio.gather(provider_task, return_exceptions=True)
                    raise asyncio.CancelledError
                return await provider_task
            finally:
                for task in (provider_task, cancellation_task):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(
                    provider_task,
                    cancellation_task,
                    return_exceptions=True,
                )

        return await run_scoped_model(complete_or_cancel)

    async def _complete_attempts(
        self,
        user_content: str,
        *,
        input_digest: str,
        proposal_schema: Mapping[str, Any],
        system_prompt: str,
        prompt_manifest: PromptReplayManifest | None,
        call_kind: str,
        max_tokens: int,
        temperature: float,
        timeout_seconds: float,
        allow_candidate_failover: bool,
    ) -> SemanticJudgmentModelResponse | None:
        response_format = _strict_response_format(proposal_schema, name=call_kind)
        messages = list(
            prepare_model_messages(
                (
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                )
            ).messages
        )
        request_token_estimate = estimate_chat_request_tokens(
            messages=messages,
            response_format=response_format,
            reserved_output_tokens=max_tokens,
        )
        if (
            prompt_manifest is not None
            and prompt_manifest.request_token_budget is not None
            and request_token_estimate > prompt_manifest.request_token_budget
        ):
            _LOGGER.warning(
                "semantic_judgment_request_token_budget_exceeded",
                extra={
                    "call_kind": call_kind,
                    "profile_id": prompt_manifest.profile_id,
                    "request_token_estimate": request_token_estimate,
                    "request_token_budget": prompt_manifest.request_token_budget,
                },
            )
            return None
        candidates = (
            self._config.candidates if allow_candidate_failover else self._config.candidates[:1]
        )
        candidate_timeout = timeout_seconds / len(candidates)
        for index, target in enumerate(candidates):
            try:
                async with asyncio.timeout(candidate_timeout):
                    token = await self._identity.get_token(target.auth_audience)
                    request = target.operation("chat/completions")
                    body: dict[str, Any] = {
                        "messages": messages,
                        "response_format": response_format,
                        **completion_body_params(
                            target.deployment,
                            temperature=temperature,
                            max_tokens=max_tokens,
                        ),
                    }
                    if (
                        call_kind == "conversation-preflight"
                        and "gpt-5" in target.deployment.casefold()
                    ):
                        body["reasoning_effort"] = "minimal"
                    if request.model_body_field is not None:
                        body["model"] = request.model_body_field
                    trace_start = start_model_trace(messages)
                    response, reservation = await call_scoped_provider(
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
                    proposal, response_content, usage = _response_mapping(response)
                    trace_call = complete_model_trace(
                        trace_start,
                        call_id=f"{call_kind}-{index + 1}",
                        kind=call_kind,
                        model=target.deployment,
                        response_content=response_content,
                        usage=usage,
                    )
                    observation = SemanticJudgmentObservation(
                        model=target.deployment,
                        usage=bounded_usage(usage),
                        trace_call=trace_call,
                        prompt_replay_manifest=prompt_manifest,
                    )
                    if reservation is not None:
                        reservation.record(observation)
                    return SemanticJudgmentModelResponse(
                        proposal=proposal,
                        observation=observation,
                    )
            except Exception as exc:  # noqa: BLE001 - bounded candidate failover
                if stop_scoped_provider_retry():
                    _LOGGER.warning(
                        "adaptive_judgment_provider_attempt_ended",
                        extra={"failure_type": type(exc).__name__},
                    )
                    return None
                failure: dict[str, Any] = {
                    "candidate_index": index,
                    "failure_type": type(exc).__name__,
                    "input_digest": input_digest,
                }
                if isinstance(exc, httpx.HTTPStatusError):
                    failure["status_code"] = exc.response.status_code
                _LOGGER.warning(f"{call_kind.replace('-', '_')}_candidate_failed", extra=failure)
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


def _strict_response_format(
    proposal_schema: Mapping[str, Any],
    *,
    name: str,
) -> dict[str, object]:
    """Return the Azure strict structured-output envelope for one proposal."""

    normalized_name = "".join(
        character
        if character.isascii() and (character.isalnum() or character in {"_", "-"})
        else "_"
        for character in name
    ).strip("_")[:64]
    if not normalized_name:
        raise ValueError("semantic response schema name MUST be non-empty")
    return {
        "type": "json_schema",
        "json_schema": {
            "name": normalized_name,
            "strict": True,
            "schema": _strict_schema_node(proposal_schema),
        },
    }


def _validate_prompt_manifest(
    prompt: str | None,
    manifest: PromptReplayManifest | None,
) -> None:
    if manifest is None:
        return
    if prompt is None or manifest.system_text_sha256 != hashlib.sha256(prompt.encode()).hexdigest():
        raise ValueError("semantic judgment prompt manifest does not match its system prompt")


def _validate_output_reserve(
    name: str,
    manifest: PromptReplayManifest | None,
    required_tokens: int,
) -> None:
    if (
        manifest is not None
        and manifest.reserved_output_tokens is not None
        and manifest.reserved_output_tokens < required_tokens
    ):
        raise ValueError(f"{name} prompt output reserve is below configured max_tokens")


def _document_query_prompt_enabled(manifest: PromptReplayManifest | None) -> bool:
    """An advertised read capability cannot silently upgrade an unrelated prompt contract."""
    return manifest is not None and any(
        layer.id == "semantic-document-query"
        and layer.version == 1
        and layer.layer is PromptLayer.PACK
        for layer in manifest.layer_manifest
    )


def _semantic_judgment_proposal_schema(
    *,
    intent_hardening_enabled: bool,
    document_query_enabled: bool = False,
    source_locale: str | None = None,
) -> dict[str, Any]:
    """Add retrieval terms only to the existing document-capable judgment call.

    Exact supplied capability identity selects the output contract, not an intent.
    Legacy callers retain their schema pin; forbidden actions still require the
    independent hardening opt-in. Query guidance stays in the generated schema,
    so configured prompts, replay manifests, budgets and observations stay intact.
    """

    schema = SemanticJudgmentProposal.model_json_schema()
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("semantic judgment proposal schema has no properties")
    schema_version = properties.get("schema_version")
    if not isinstance(schema_version, dict):
        raise ValueError("semantic judgment proposal schema has no version property")
    if not intent_hardening_enabled:
        properties.pop("forbidden_actions", None)
    if not document_query_enabled:
        properties.pop("document_query", None)
        schema.get("$defs", {}).pop("DocumentRetrievalQuery", None)
    elif source_locale is not None:
        if source_locale not in {"en", "ko"}:
            raise ValueError("document retrieval source locale MUST be en or ko")
        schema["$defs"]["DocumentRetrievalQuery"]["properties"]["source_locale"] = {
            "type": "string",
            "const": source_locale,
        }
    schema_version.clear()
    schema_version["const"] = (
        "1.2.0" if document_query_enabled else "1.1.0" if intent_hardening_enabled else "1.0.0"
    )
    schema_version["type"] = "string"
    return schema


def _strict_schema_node(value: object) -> object:
    if isinstance(value, Mapping):
        normalized = {
            str(key): _strict_schema_node(item)
            for key, item in value.items()
            if key not in _UNSUPPORTED_STRICT_SCHEMA_KEYS
        }
        properties = normalized.get("properties")
        if isinstance(properties, Mapping):
            normalized["additionalProperties"] = False
            normalized["required"] = list(properties)
        return normalized
    if isinstance(value, list):
        return [_strict_schema_node(item) for item in value]
    return value


__all__ = [
    "AzureOpenAISemanticJudgmentModel",
    "AzureOpenAISemanticJudgmentModelConfig",
]
