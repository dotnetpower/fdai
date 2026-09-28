"""Azure OpenAI adapter for the shadow question-form and concept-selection calls.

Both calls return one strict JSON object and never carry authority. The question
form quotes utterance text instead of counting characters, and concept selection
sees one complete catalog shard per call. Exact identifiers reach the model only
as opaque placeholders, and a form call whose input still needs redaction or
exceeds its request ceiling is refused with a typed reason. Transport failure
returns ``None`` so the shadow runner records ``model_unavailable``. Recorded
traces are content-free: hashes, usage, timing, and redaction counts only.
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

from fdai.core.conversation.adaptive_call_scope import (
    call_scoped_provider,
    run_scoped_model,
    stop_scoped_provider_retry,
)
from fdai.core.conversation.model_observation import ConversationModelObservation
from fdai.core.conversation.semantic_reasoning_concepts import ConceptShard
from fdai.core.conversation.semantic_reasoning_proposal import (
    FormInputHeldError,
    question_form_proposal_schema,
)
from fdai.core.conversation.semantic_reasoning_repair import FormRepair
from fdai.core.conversation.semantic_reasoning_review import extraction_schema
from fdai.core.prompts import PromptReplayManifest, estimate_chat_request_tokens
from fdai.delivery.azure.llm.completion_body import completion_body_params
from fdai.delivery.azure.llm.identity_masking import IdentityMask
from fdai.delivery.azure.llm.input_detection import (
    contained,
    detection_copies,
    identity_matches,
    identity_segments,
    labels_secret,
    redact_text,
    secret_spans,
)
from fdai.delivery.azure.llm.model_trace import (
    ModelInputMinimizationError,
    bounded_usage,
    complete_model_trace,
    prepare_model_messages,
    start_model_trace,
)
from fdai.delivery.azure.llm.request_target import ModelRequestTarget
from fdai.delivery.azure.llm.semantic_judgment import _strict_response_format
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger(__name__)
_MAX_CANDIDATES = 8
_MAX_PROMPT_CHARS = 32_768
_MAX_RESPONSE_BYTES = 65_536
_MAX_REQUEST_TOKENS = 131_072
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
                    "candidate_ids": {"type": "array", "items": {"type": "string"}},
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
    # Without an extraction prompt the review is unavailable, so no shadow turn is released.
    extraction_system_prompt: str | None = None
    extraction_prompt_manifest: PromptReplayManifest | None = None
    # A different model family for the blind extraction keeps its errors independent.
    extraction_candidates: tuple[ModelRequestTarget, ...] = ()
    timeout_seconds: float = 30.0
    form_max_tokens: int = 2_048
    concept_max_tokens: int = 512
    extraction_max_tokens: int = 1_024
    # Matches the active profiles' request budget; a manifest budget can only lower it.
    max_request_tokens: int = 32_768

    def __post_init__(self) -> None:
        if not 1 <= len(self.candidates) <= _MAX_CANDIDATES:
            raise ValueError(f"question form candidates MUST contain 1 to {_MAX_CANDIDATES}")
        for prompt, manifest in (
            (self.form_system_prompt, self.form_prompt_manifest),
            (self.concept_system_prompt, self.concept_prompt_manifest),
            *(
                ((self.extraction_system_prompt, self.extraction_prompt_manifest),)
                if self.extraction_system_prompt is not None
                else ()
            ),
        ):
            if not prompt or len(prompt) > _MAX_PROMPT_CHARS:
                raise ValueError("question form prompts MUST be non-empty and bounded")
            if manifest is not None and (
                manifest.system_text_sha256 != hashlib.sha256(prompt.encode()).hexdigest()
            ):
                raise ValueError("question form prompt manifest does not match its prompt")
        if not 0 < self.timeout_seconds <= 120:
            raise ValueError("question form timeout_seconds MUST be in (0, 120]")
        if (
            not 1 <= self.form_max_tokens <= 4_096
            or not 1 <= self.concept_max_tokens <= 2_048
            or not 1 <= self.extraction_max_tokens <= 2_048
            or len(self.extraction_candidates) > _MAX_CANDIDATES
        ):
            raise ValueError("question form output token bounds are out of range")
        if not 1 <= self.max_request_tokens <= _MAX_REQUEST_TOKENS:
            raise ValueError("question form request token ceiling is out of range")
        for manifest, max_tokens in (
            (self.form_prompt_manifest, self.form_max_tokens),
            (self.concept_prompt_manifest, self.concept_max_tokens),
            (self.extraction_prompt_manifest, self.extraction_max_tokens),
        ):
            if (
                manifest is not None
                and manifest.reserved_output_tokens is not None
                and manifest.reserved_output_tokens < max_tokens
            ):
                raise ValueError("question form output tokens exceed the prompt reserve")


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
        self._extraction_schema = extraction_schema()

    async def propose_form(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        locale: str,
        pass_index: int,
        prior_goals: tuple[dict[str, Any], ...],
        repair: FormRepair | None = None,
    ) -> Mapping[str, Any] | None:
        if len(context) > _MAX_CONTEXT_ITEMS:
            # Only the most recent history is context for the form; the question is never cut.
            _LOGGER.info(
                "question_form_context_bounded",
                extra={"dropped_items": len(context) - _MAX_CONTEXT_ITEMS},
            )
            context = context[-_MAX_CONTEXT_ITEMS:]
        # Secrets are found in the raw text, before masking or encoding can hide their shape.
        if any(_exposes_secret(text) for text in (utterance, *context)):
            _held("input_redacted", name="semantic-question-form", raise_error=True)
        mask = IdentityMask(utterance, context)
        payload: dict[str, Any] = {
            "utterance": mask.utterance,
            "context": list(mask.context),
            "locale": locale,
            "pass_index": pass_index,
            "prior_goals": list(prior_goals),
        }
        if repair is not None:
            payload["repair"] = {
                "previous_form": mask.mask_form(repair.previous),
                "violations": [mask.mask_text(item) for item in repair.violations],
            }
        # Every other string leaf is checked after masking, so nothing but a placeholder
        # stands for an identifier and any secret, however encoded, holds the call.
        others = {key: value for key, value in payload.items() if key not in _CHECKED_KEYS}
        if any(
            secret_spans(leaf) or _hides_secret(leaf) or _hides_identity(leaf)
            for leaf in _string_leaves(others)
        ):
            _held("input_redacted", name="semantic-question-form", raise_error=True)
        # Quotes must match the operator's exact words, so a redacted input cannot be judged.
        proposal = await self._complete(
            system_prompt=self._config.form_system_prompt,
            user_payload=payload,
            schema=self._form_schema,
            name="semantic-question-form",
            max_tokens=self._config.form_max_tokens,
            manifest=self._config.form_prompt_manifest,
            require_verbatim=True,
        )
        return mask.unmask_form(proposal) if proposal is not None else None

    async def choose_concepts(
        self,
        *,
        utterance: str,
        mentions: tuple[dict[str, Any], ...],
        shard: ConceptShard,
    ) -> Mapping[str, Any] | None:
        shard_payload = shard.payload()
        # Catalog strings are reviewed data, but any that decodes to a secret or an exact
        # identifier holds the call rather than being altered, and so does operator text
        # whose secret or identifier only decoding or record structure reveals.
        if any(
            secret_spans(leaf) or _hides_secret(leaf) or _hides_identity(leaf)
            for leaf in _string_leaves(shard_payload)
        ) or any(
            # Operator text with any secret is withheld whole, never partly redacted.
            secret_spans(leaf) or _hides_secret(leaf) or _hides_identity(leaf)
            for leaf in _string_leaves([utterance, list(mentions)])
        ):
            _held("input_redacted", name="semantic-concept-selection", raise_error=False)
            return None
        # Concept choice needs no verbatim quotes, so raw text is redacted before encoding.
        payload = {
            "utterance": redact_text(utterance),
            "mentions": [_redacted(item) for item in mentions],
            "shard_digest": shard.digest,
            "shard": shard_payload,
        }
        return await self._complete(
            system_prompt=self._config.concept_system_prompt,
            user_payload=payload,
            schema=_CONCEPT_CHOICE_SCHEMA,
            name="semantic-concept-selection",
            max_tokens=self._config.concept_max_tokens,
            manifest=self._config.concept_prompt_manifest,
            require_verbatim=False,
        )

    async def extract_constraints(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        locale: str,
    ) -> Mapping[str, Any] | None:
        """Ask the independent extractor for every constraint the question states.

        The extractor sees only the question, never the proposed form, so it cannot
        repeat the proposer's reading.
        """

        if self._config.extraction_system_prompt is None:
            return None
        context = context[-_MAX_CONTEXT_ITEMS:]
        if any(_exposes_secret(text) for text in (utterance, *context)):
            _held("input_redacted", name="semantic-constraint-extraction", raise_error=True)
        mask = IdentityMask(utterance, context)
        payload: dict[str, Any] = {
            "utterance": mask.utterance,
            "context": list(mask.context),
            "locale": locale,
        }
        extraction = await self._complete(
            system_prompt=self._config.extraction_system_prompt,
            user_payload=payload,
            schema=self._extraction_schema,
            name="semantic-constraint-extraction",
            max_tokens=self._config.extraction_max_tokens,
            manifest=self._config.extraction_prompt_manifest,
            require_verbatim=True,
            candidates=self._config.extraction_candidates or None,
        )
        if extraction is None:
            return None
        constraints = extraction.get("constraints")
        if not isinstance(constraints, list):
            return extraction
        # Quotes point at the masked question, so each maps back to the exact words.
        return {
            **extraction,
            "constraints": [
                {**item, "quote": mask.unmask_quote(item["quote"])}
                if isinstance(item, Mapping) and isinstance(item.get("quote"), Mapping)
                else item
                for item in constraints
            ],
        }

    async def _complete(
        self,
        *,
        system_prompt: str,
        user_payload: Mapping[str, Any],
        schema: Mapping[str, Any],
        name: str,
        max_tokens: int,
        manifest: PromptReplayManifest | None,
        require_verbatim: bool,
        candidates: tuple[ModelRequestTarget, ...] | None = None,
    ) -> Mapping[str, Any] | None:
        try:
            prepared = prepare_model_messages(
                (
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(user_payload, ensure_ascii=False, sort_keys=True),
                    },
                )
            )
        except ModelInputMinimizationError:
            _held("input_held", name=name, raise_error=require_verbatim)
            return None
        if require_verbatim and prepared.receipt.redaction_replacement_count:
            _held("input_redacted", name=name, raise_error=True)
            return None
        # Every serialized message gets the same decoded checks, so nothing that encoding or
        # serialization could still hide is transmitted.
        if any(
            isinstance(content := message.get("content"), str)
            and (_hides_secret(content) or _hides_identity(content))
            for message in prepared.messages
        ):
            _held("input_redacted", name=name, raise_error=require_verbatim)
            return None
        messages = list(prepared.messages)
        response_format = _strict_response_format(schema, name=name)
        estimate = estimate_chat_request_tokens(
            messages=messages, response_format=response_format, reserved_output_tokens=max_tokens
        )
        ceiling = self._config.max_request_tokens
        if manifest is not None and manifest.request_token_budget is not None:
            ceiling = min(ceiling, manifest.request_token_budget)
        if estimate > ceiling:
            _held("request_budget_exceeded", name=name, raise_error=require_verbatim)
            return None

        async def attempt() -> Mapping[str, Any] | None:
            return await self._attempt(
                messages=messages,
                response_format=response_format,
                name=name,
                max_tokens=max_tokens,
                manifest=manifest,
                candidates=candidates or self._config.candidates,
            )

        return await run_scoped_model(attempt)

    async def _attempt(
        self,
        *,
        messages: list[dict[str, Any]],
        response_format: Mapping[str, Any],
        name: str,
        max_tokens: int,
        manifest: PromptReplayManifest | None,
        candidates: tuple[ModelRequestTarget, ...],
    ) -> Mapping[str, Any] | None:
        candidate_timeout = self._config.timeout_seconds / len(candidates)
        for index, target in enumerate(candidates):
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
                    payload, content, usage = _content_object(response)
                    if reservation is not None:
                        reservation.record(
                            ConversationModelObservation(
                                model=target.deployment,
                                usage=bounded_usage(usage),
                                trace_call=_content_free(
                                    complete_model_trace(
                                        trace_start,
                                        call_id=f"{name}-{index + 1}",
                                        kind=name,
                                        model=target.deployment,
                                        response_content=content,
                                        usage=usage,
                                    )
                                ),
                                prompt_replay_manifest=manifest,
                            )
                        )
                    return payload
            except Exception as exc:  # noqa: BLE001 - bounded candidate failover
                if stop_scoped_provider_retry():
                    _LOGGER.warning(
                        "question_form_provider_attempt_ended",
                        extra={"call_kind": name, "failure_type": type(exc).__name__},
                    )
                    return None
                failure: dict[str, Any] = {
                    "call_kind": name,
                    "candidate_index": index,
                    "failure_type": type(exc).__name__,
                }
                if isinstance(exc, httpx.HTTPStatusError):
                    failure["status_code"] = exc.response.status_code
                _LOGGER.warning("question_form_candidate_failed", extra=failure)
        return None


def _exposes_secret(text: str) -> bool:
    """Return whether any secret could reach the model through the masked text.

    On the raw text, a secret is hidden only inside the exact span a placeholder will
    replace. A secret that appears in any decoded escape layer, or once backslashes are
    removed, is held outright, because masking works on the raw text and could not hide it,
    and so is text whose escapes do not finish decoding within the layer bound.
    """

    if labels_secret(text) or not contained(sorted(secret_spans(text)), identity_segments(text)):
        return True
    return _hides_secret(text) or _hides_identity(text)


def _hides_secret(text: str) -> bool:
    """Return whether decoding or record structure reveals a secret, or decoding cannot
    finish, which fails closed."""

    copies, complete = detection_copies(text)
    return (
        not complete
        or any(secret_spans(copy) for copy in copies[1:])
        or any(labels_secret(copy) for copy in copies)
    )


def _hides_identity(text: str) -> bool:
    """Return whether decoding reveals an exact identifier that masking would not hide.

    Masking finds identifiers in the raw text only. Each raw identifier span is blanked
    first, so decoding checks only the remaining text, and any identifier found there,
    even a duplicate of a masked one, could reach the model and holds the call.
    """

    blanked = _blanked(text, identity_segments(text))
    copies, complete = detection_copies(blanked)
    if not complete:
        return True
    return any(identity_matches(copy) for copy in copies[1:])


def _blanked(text: str, spans: tuple[tuple[int, int], ...]) -> str:
    parts: list[str] = []
    cursor = 0
    for start, end in spans:
        parts.extend((text[cursor:start], " "))
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def _concept_text(text: str) -> str:
    """Return raw text safe for concept selection, or the redaction marker when decoding
    reveals a secret or an identifier that raw redaction could not remove."""

    if _hides_secret(text) or _hides_identity(text):
        return "[REDACTED]"
    return redact_text(text)


_CHECKED_KEYS = frozenset({"utterance", "context"})


def _string_leaves(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [
            leaf
            for key, item in value.items()
            for leaf in (*_string_leaves(key), *_string_leaves(item))
        ]
    if isinstance(value, list | tuple):
        return [leaf for item in value for leaf in _string_leaves(item)]
    return []


def _redacted(value: Any) -> Any:
    if isinstance(value, str):
        return _concept_text(value)
    if isinstance(value, Mapping):
        return {key: _redacted(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_redacted(item) for item in value]
    return value


def _held(reason: str, *, name: str, raise_error: bool) -> None:
    _LOGGER.warning("question_form_call_held", extra={"call_kind": name, "reason": reason})
    if raise_error:
        raise FormInputHeldError(reason)


def _content_free(trace: Mapping[str, object]) -> dict[str, object]:
    """Keep hashes, usage, timing, and redaction counts; drop every message and reply text."""

    request = trace.get("request")
    response = trace.get("response")
    return {
        **trace,
        "request": {
            "messages": [],
            "sha256": request.get("sha256") if isinstance(request, Mapping) else None,
        },
        "response": {
            "role": "assistant",
            "content": "",
            "sha256": response.get("sha256") if isinstance(response, Mapping) else None,
        },
    }


def _content_object(
    response: httpx.Response,
) -> tuple[Mapping[str, Any] | None, str, Mapping[str, Any] | None]:
    envelope = response.json()
    usage = envelope.get("usage") if isinstance(envelope, Mapping) else None
    bounded = usage if isinstance(usage, Mapping) else None
    choices = envelope.get("choices") if isinstance(envelope, Mapping) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        return None, "", bounded
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, str) or len(content.encode()) > _MAX_RESPONSE_BYTES:
        return None, "", bounded
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None, content, bounded
    return (payload if isinstance(payload, Mapping) else None), content, bounded


__all__ = ["AzureOpenAIQuestionFormConfig", "AzureOpenAIQuestionFormModel"]
