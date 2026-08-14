"""Pure validation and payload helpers for the service-local narrator."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from fdai_operator_service.adapters.narrator_latency import NarratorTarget

_MAX_CANDIDATES = 8
_MAX_SSE_LINE_CHARS = 131_072


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

    context = body.get("view_context")
    history = body.get("history")
    context_text = json.dumps(context, ensure_ascii=False, sort_keys=True)[:24_000]
    messages = [
        {
            "role": "system",
            "content": (
                "You are Bragi, the FDAI presentation narrator. Answer the operator directly. "
                "Use only supplied screen context or clearly label general model knowledge. "
                "Never claim current cloud state without evidence and never approve or execute "
                "actions."
            ),
        },
        {"role": "system", "content": f"Current screen context: {context_text}"},
    ]
    if isinstance(history, list):
        for item in history[-12:]:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and isinstance(content, str) and content:
                messages.append({"role": role, "content": content[:8_000]})
    messages.append({"role": "user", "content": prompt})
    return messages


def has_images(body: Mapping[str, Any]) -> bool:
    """Detect only server-supported image reference fields."""

    for key in ("images", "image_ids"):
        value = body.get(key)
        if isinstance(value, list) and value:
            return True
    return False


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

    if len(line) > _MAX_SSE_LINE_CHARS:
        raise ValueError("narrator SSE line exceeds the size limit")
    if not line.startswith("data:"):
        return None
    raw = line.removeprefix("data:").strip()
    if not raw or raw == "[DONE]":
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("narrator SSE data is malformed") from exc
    if not isinstance(payload, dict):
        raise ValueError("narrator SSE data MUST be an object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("narrator SSE choices are malformed")
    delta = choices[0].get("delta")
    if not isinstance(delta, dict):
        raise ValueError("narrator SSE delta is malformed")
    content = delta.get("content")
    if content is None:
        return None
    if not isinstance(content, str):
        raise ValueError("narrator SSE content MUST be text")
    return content if content else None


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
    "has_images",
    "is_reasoning_model",
    "narrator_messages",
    "narrator_targets",
    "stream_delta",
    "vision_probe_content",
    "vision_targets",
]
