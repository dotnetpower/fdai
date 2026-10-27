"""Pure validation and payload helpers for the service-local narrator."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from fdai_service_contracts.dialogue_state import DialogueState

from fdai_operator_service.adapters.narrator_dialogue_shadow import shadow_dialogue_state
from fdai_operator_service.adapters.narrator_latency import NarratorTarget
from fdai_operator_service.adapters.narrator_token_budget import (
    NarratorContextReceipt,
    bounded_json,
    chat_request_tokens,
    fit_text,
)
from fdai_operator_service.families.conversation.inline_images import inline_images_present

_MAX_CANDIDATES = 8
_MAX_SSE_LINE_CHARS = 131_072
NARRATOR_REQUEST_TOKEN_BUDGET = 8_192
NARRATOR_RESERVED_OUTPUT_TOKENS = 1_024
_CONTEXT_TOKEN_BUDGET = 2_048
_MIN_HISTORY_TOKENS = 32
_SYSTEM_PROMPT = (
    "You are Bragi, the FDAI presentation narrator. Answer the operator directly. "
    "FDAI is the autonomous cloud-operations control plane for Resilience, Change "
    "Safety, and Cost Governance; SRE/SLO is its operating model. Treat FDAI as the "
    "product name and do not invent or expand an acronym. "
    "Use only supplied screen context or clearly label general model knowledge. "
    "Never claim current cloud state without evidence and never approve or execute actions."
)


@dataclass(frozen=True, slots=True)
class NarratorMessagePlan:
    """Bounded messages and content-free selection accounting for one model."""

    messages: list[dict[str, Any]]
    receipt: NarratorContextReceipt
    dialogue_state: DialogueState


def narrator_targets(payload: object) -> tuple[NarratorTarget, ...]:
    """Return the bounded text candidate pool from one resolved-model artifact."""

    targets = _candidate_targets(payload, key="narrator_candidates", fallback_key="narrator")
    if not targets:
        raise ValueError("resolved narrator artifact contains no usable narrator candidate")
    return targets


def vision_targets(payload: object) -> tuple[NarratorTarget, ...]:
    """Return the independently provisioned vision candidate pool."""

    return _candidate_targets(payload, key="vision_candidates")


def narrator_messages(prompt: str, body: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build bounded narrator messages without adding evidence or authority."""

    return narrator_message_plan(prompt, body, model="gpt-5").messages


def narrator_message_plan(
    prompt: str,
    body: Mapping[str, Any],
    *,
    model: str,
) -> NarratorMessagePlan:
    """Fit screen context and newest history into the narrator request budget."""

    context = body.get("view_context")
    history = body.get("history")
    declared_history_count = body.get("history_total_count")
    context_text, context_shortened = bounded_json(
        context,
        model=model,
        token_budget=_CONTEXT_TOKEN_BUDGET,
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "system", "content": f"Current screen context: {context_text}"},
    ]
    valid_history: list[tuple[str, str]] = []
    if isinstance(history, list):
        for item in history:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and isinstance(content, str) and content:
                valid_history.append((role, content))
    prompt_message = {"role": "user", "content": prompt}
    if (
        chat_request_tokens(
            [*messages, prompt_message],
            model=model,
            reserved_output_tokens=NARRATOR_RESERVED_OUTPUT_TOKENS,
        )
        > NARRATOR_REQUEST_TOKEN_BUDGET
    ):
        raise ValueError("narrator prompt and required context exceed the request token budget")
    selected: list[dict[str, Any]] = []
    shortened = 0
    for role, content in reversed(valid_history[-12:]):
        candidate = {"role": role, "content": content}
        trial = [*messages, candidate, *selected, prompt_message]
        if (
            chat_request_tokens(
                trial,
                model=model,
                reserved_output_tokens=NARRATOR_RESERVED_OUTPUT_TOKENS,
            )
            <= NARRATOR_REQUEST_TOKEN_BUDGET
        ):
            selected.insert(0, candidate)
            continue
        base_tokens = chat_request_tokens(
            [*messages, *selected, prompt_message],
            model=model,
            reserved_output_tokens=NARRATOR_RESERVED_OUTPUT_TOKENS,
        )
        empty_message_tokens = (
            chat_request_tokens(
                [*messages, {"role": role, "content": ""}, *selected, prompt_message],
                model=model,
                reserved_output_tokens=NARRATOR_RESERVED_OUTPUT_TOKENS,
            )
            - base_tokens
        )
        remaining = NARRATOR_REQUEST_TOKEN_BUDGET - base_tokens - empty_message_tokens
        fitted, was_shortened = fit_text(content, model=model, token_budget=max(remaining, 0))
        if was_shortened and len(fitted) >= _MIN_HISTORY_TOKENS:
            selected.insert(0, {"role": role, "content": fitted})
            shortened += 1
        break
    messages.extend(selected)
    messages.append(prompt_message)
    estimate = chat_request_tokens(
        messages,
        model=model,
        reserved_output_tokens=NARRATOR_RESERVED_OUTPUT_TOKENS,
    )
    source_history_items = (
        declared_history_count
        if isinstance(declared_history_count, int)
        and not isinstance(declared_history_count, bool)
        and len(valid_history) <= declared_history_count <= 1_000_000
        else len(valid_history)
    )
    return NarratorMessagePlan(
        messages=messages,
        dialogue_state=shadow_dialogue_state(valid_history, kept=len(selected)),
        receipt=NarratorContextReceipt(
            request_token_estimate=estimate,
            request_token_budget=NARRATOR_REQUEST_TOKEN_BUDGET,
            reserved_output_tokens=NARRATOR_RESERVED_OUTPUT_TOKENS,
            source_history_items=source_history_items,
            included_history_items=len(selected),
            omitted_history_items=max(source_history_items - len(selected), 0),
            shortened_history_items=shortened,
            context_shortened=context_shortened,
        ),
    )


def has_images(body: Mapping[str, Any]) -> bool:
    """Detect Console payloads and image references before any narrator provider call."""

    return inline_images_present(body)


def vision_probe_content() -> list[dict[str, Any]]:
    """Return the bounded one-pixel image probe payload."""

    return [
        {"type": "text", "text": "Return OK for this probe image."},
        {
            "type": "image_url",
            "image_url": {
                "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB",
                "detail": "low",
            },
        },
    ]


def stream_delta(line: str) -> str | None:
    """Decode one non-empty Azure chat-completion SSE text delta."""

    return stream_payload(line)[0]


def stream_payload(line: str) -> tuple[str | None, dict[str, int] | None]:
    """Decode one SSE text delta and bounded provider token usage."""

    if len(line) > _MAX_SSE_LINE_CHARS:
        raise ValueError("narrator SSE line exceeds the size limit")
    if not line.startswith("data:"):
        return None, None
    raw = line.removeprefix("data:").strip()
    if not raw or raw == "[DONE]":
        return None, None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("narrator SSE data is malformed") from exc
    if not isinstance(payload, dict):
        raise ValueError("narrator SSE data MUST be an object")
    usage = _bounded_usage(payload.get("usage"))
    choices = payload.get("choices")
    if choices == [] and any(
        isinstance(payload.get(key), expected_type)
        for key, expected_type in (
            ("prompt_filter_results", list),
            ("prompt_annotations", list),
            ("usage", dict),
        )
    ):
        return None, usage
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("narrator SSE choices are malformed")
    choice = choices[0]
    delta = choice.get("delta")
    if delta is None and (
        isinstance(choice.get("content_filter_results"), dict)
        or choice.get("finish_reason") == "stop"
    ):
        return None, usage
    if not isinstance(delta, dict):
        raise ValueError("narrator SSE delta is malformed")
    content = delta.get("content")
    if content is None:
        return None, usage
    if not isinstance(content, str):
        raise ValueError("narrator SSE content MUST be text")
    return content if content else None, usage


def _bounded_usage(value: object) -> dict[str, int] | None:
    if not isinstance(value, Mapping):
        return None
    result = {
        key: item
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        if isinstance((item := value.get(key)), int) and not isinstance(item, bool) and item >= 0
    }
    details = value.get("prompt_tokens_details")
    cached = details.get("cached_tokens") if isinstance(details, Mapping) else None
    if isinstance(cached, int) and not isinstance(cached, bool) and cached >= 0:
        result["cached_tokens"] = cached
    return result or None


def is_reasoning_model(deployment: str) -> bool:
    """Select the bounded token parameter accepted by reasoning deployments."""

    normalized = deployment.casefold()
    return any(token in normalized for token in ("gpt-5", "o1", "o3", "o4"))


def _candidate_targets(
    payload: object,
    *,
    key: str,
    fallback_key: str | None = None,
) -> tuple[NarratorTarget, ...]:
    if not isinstance(payload, dict):
        raise ValueError("resolved narrator artifact MUST be an object")
    raw = payload.get(key)
    candidates = raw if isinstance(raw, list) and raw else []
    if len(candidates) > _MAX_CANDIDATES:
        raise ValueError(f"resolved narrator {key} exceeds the candidate limit")
    if not candidates and fallback_key is not None:
        candidates = [payload.get(fallback_key)]
    targets: list[NarratorTarget] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        endpoint = candidate.get("endpoint")
        deployment = candidate.get("deployment")
        api_version = candidate.get("api_version", "2024-08-01-preview")
        if (
            isinstance(endpoint, str)
            and _is_allowed_endpoint(endpoint)
            and isinstance(deployment, str)
            and deployment.strip()
            and isinstance(api_version, str)
            and api_version.strip()
        ):
            targets.append(NarratorTarget(endpoint.rstrip("/"), deployment, api_version))
    return tuple(targets)


def _is_allowed_endpoint(endpoint: str) -> bool:
    parsed = urlparse(endpoint)
    hostname = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and port in {None, 443}
        and parsed.path in {"", "/"}
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
        and hostname.endswith(".openai.azure.com")
    )


__all__ = [
    "NARRATOR_REQUEST_TOKEN_BUDGET",
    "NARRATOR_RESERVED_OUTPUT_TOKENS",
    "has_images",
    "is_reasoning_model",
    "narrator_message_plan",
    "narrator_messages",
    "narrator_targets",
    "stream_delta",
    "stream_payload",
    "vision_probe_content",
    "vision_targets",
]
