"""Build bounded redacted observations for already-issued model calls."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

_MAX_MESSAGES: Final[int] = 24
_MAX_REQUEST_CHARS: Final[int] = 12_000
_MAX_RESPONSE_CHARS: Final[int] = 6_000
_TRUNCATED: Final[str] = "\n[TRUNCATED]"
_REDACTED: Final[str] = "[REDACTED]"
_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("inline-image", re.compile(r"(?i)data:image/[a-z0-9.+-]+;base64,[a-z0-9+/=_\r\n-]+")),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")),
    (
        "named-secret",
        re.compile(
            r"(?i)\b(?:password|secret|token|api[_-]?key)[\"']?\s*[:=]\s*"
            r"[\"']?[^\s,;\"'}]+"
        ),
    ),
    ("jwt", re.compile(r"\beyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b")),
    ("azure-resource-id", re.compile(r"(?i)/subscriptions/[0-9a-f-]+(?:/[^\s\"'<>]+)+")),
    (
        "guid",
        re.compile(
            r"(?i)(?<![0-9a-f])"
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
            r"(?![0-9a-f])"
        ),
    ),
    ("email", re.compile(r"(?i)\b[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}\b")),
    ("ip-address", re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")),
    ("url", re.compile(r"(?i)https?://[^\s\"'<>]+")),
    ("sas-value", re.compile(r"(?i)(?:\?|&)(?:sig|se|sp|sv|st|spr)=[^&\s\"'<>]+")),
)


@dataclass(frozen=True, slots=True)
class ModelTraceStart:
    """Sanitized request state and timing for one provider call."""

    started_at: str
    started_monotonic: float
    request: dict[str, object]
    redactions: Counter[str]


def start_model_trace(messages: Sequence[Mapping[str, Any]]) -> ModelTraceStart:
    """Capture a bounded sanitized request without retaining provider credentials."""
    sanitized, redactions = _sanitize_messages(messages)
    return ModelTraceStart(
        started_at=_now(),
        started_monotonic=time.monotonic(),
        request={"messages": sanitized, "sha256": _sha256(_canonical(messages))},
        redactions=redactions,
    )


def complete_model_trace(
    start: ModelTraceStart,
    *,
    call_id: str,
    kind: str,
    model: str,
    response_content: str,
    usage: Mapping[str, Any] | None,
) -> dict[str, object]:
    """Return one Console-compatible redacted model-call trace."""
    redacted, response_redactions = _redact(response_content, max_chars=_MAX_RESPONSE_CHARS)
    redactions = start.redactions.copy()
    redactions.update(response_redactions)
    return {
        "call_id": call_id[:128],
        "kind": kind[:128],
        "model": model[:128],
        "status": "completed",
        "started_at": start.started_at,
        "completed_at": _now(),
        "duration_ms": max(0, int((time.monotonic() - start.started_monotonic) * 1_000)),
        "request": start.request,
        "response": {
            "role": "assistant",
            "content": redacted,
            "sha256": _sha256(response_content),
        },
        "usage": bounded_usage(usage),
        "redactions": [
            {"rule": rule, "replacements": count} for rule, count in sorted(redactions.items())
        ],
    }


def bounded_usage(value: Mapping[str, Any] | None) -> dict[str, int] | None:
    """Keep only measured non-negative provider token counters."""
    if value is None:
        return None
    output = {
        key: item
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        if isinstance((item := value.get(key)), int) and not isinstance(item, bool) and item >= 0
    }
    return output or None


def _sanitize_messages(
    messages: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, str]], Counter[str]]:
    output: list[dict[str, str]] = []
    redactions: Counter[str] = Counter()
    remaining = _MAX_REQUEST_CHARS
    for message in messages[:_MAX_MESSAGES]:
        role = message.get("role")
        if role not in {"system", "user", "assistant", "tool"}:
            continue
        content = _text_content(message.get("content"), redactions)
        bounded, content_redactions = _redact(content, max_chars=max(0, remaining))
        redactions.update(content_redactions)
        output.append({"role": str(role), "content": bounded})
        remaining = max(0, remaining - len(bounded))
        if remaining == 0:
            break
    if len(messages) > _MAX_MESSAGES:
        redactions["message-limit"] += len(messages) - _MAX_MESSAGES
    return output, redactions


def _text_content(value: Any, redactions: Counter[str]) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        redactions["non-text-content"] += 1
        return "[NON_TEXT_CONTENT_REDACTED]"
    parts: list[str] = []
    for item in value:
        if (
            isinstance(item, Mapping)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
        ):
            parts.append(str(item["text"]))
        else:
            parts.append("[NON_TEXT_CONTENT_REDACTED]")
            redactions["non-text-content"] += 1
    return "\n".join(parts)


def _redact(value: str, *, max_chars: int) -> tuple[str, Counter[str]]:
    output = value
    redactions: Counter[str] = Counter()
    for rule, pattern in _PATTERNS:
        output, count = pattern.subn(_REDACTED, output)
        if count:
            redactions[rule] += count
    if len(output) > max_chars:
        keep = max(0, max_chars - len(_TRUNCATED))
        output = f"{output[:keep]}{_TRUNCATED}"[:max_chars]
        redactions["character-limit"] += 1
    return output, redactions


def _canonical(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError):
        return repr(value)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


__all__ = ["bounded_usage", "complete_model_trace", "start_model_trace"]
