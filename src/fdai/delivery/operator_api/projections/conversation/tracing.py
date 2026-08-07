"""Opt-in, request-local redacted model request and response traces.

Responsibility: Collect and project bounded redacted model-call evidence.
Boundary: Accept in-process request and response values without invoking a model.
Authority and state: Read-only, request-local, and free of durable writes.
Dependencies: Python context, hashing, matching, and serialization primitives.
Deployment: Runs in-process within the Operator API without a network boundary.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

_SCHEMA_VERSION: Final[int] = 1
_MAX_CALLS: Final[int] = 8
_MAX_MESSAGES_PER_CALL: Final[int] = 24
_MAX_REQUEST_CHARS_PER_CALL: Final[int] = 12_000
_MAX_RESPONSE_CHARS_PER_CALL: Final[int] = 6_000
_TRUNCATED: Final[str] = "\n[TRUNCATED]"
_REDACTED: Final[str] = "[REDACTED]"
_CURRENT_VIEW_SNAPSHOT: Final[re.Pattern[str]] = re.compile(
    r"(?s)Current view snapshot \(JSON\):\n.*$"
)

_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("inline-image", re.compile(r"(?i)data:image/[a-z0-9.+-]+;base64,[a-z0-9+/=_-]+")),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")),
    (
        "named-secret",
        re.compile(
            r"(?i)\b(?:password|secret|token|api[_-]?key)[\"']?\s*[:=]\s*"
            r"[\"']?[^\s,;\"'}]+"
        ),
    ),
    ("jwt", re.compile(r"\beyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b")),
    (
        "azure-resource-id",
        re.compile(r"(?i)/subscriptions/[0-9a-f-]+(?:/[^\s\"'<>]+)+"),
    ),
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


@dataclass(slots=True)
class _ModelCall:
    call_id: str
    kind: str
    model: str
    started_at: str
    started_monotonic: float
    request_messages: list[dict[str, str]]
    request_sha256: str
    redactions: Counter[str]
    status: str = "incomplete"
    completed_at: str | None = None
    duration_ms: int | None = None
    response_content: str | None = None
    response_sha256: str | None = None
    usage: dict[str, int] | None = None


@dataclass(slots=True)
class ModelTraceCollector:
    calls: list[_ModelCall] = field(default_factory=list)
    omitted_calls: int = 0


@dataclass(frozen=True, slots=True)
class ModelTraceScope:
    collector: ModelTraceCollector | None
    token: Token[ModelTraceCollector | None]


_ACTIVE_TRACE: Final[ContextVar[ModelTraceCollector | None]] = ContextVar(
    "fdai_chat_model_trace",
    default=None,
)


def activate_model_trace(enabled: bool) -> ModelTraceScope:
    """Activate an isolated collector; disabled scopes suppress any parent trace."""

    collector = ModelTraceCollector() if enabled else None
    return ModelTraceScope(collector=collector, token=_ACTIVE_TRACE.set(collector))


def deactivate_model_trace(scope: ModelTraceScope) -> None:
    _ACTIVE_TRACE.reset(scope.token)


def begin_model_call(
    *,
    kind: str,
    model: str,
    messages: Sequence[Mapping[str, Any]],
) -> _ModelCall | None:
    collector = _ACTIVE_TRACE.get()
    if collector is None:
        return None
    if len(collector.calls) >= _MAX_CALLS:
        collector.omitted_calls += 1
        return None
    sanitized, redactions = _sanitize_messages(messages)
    call = _ModelCall(
        call_id=f"model-call-{len(collector.calls) + 1}",
        kind=_bounded_label(kind),
        model=_bounded_label(model),
        started_at=_now(),
        started_monotonic=time.monotonic(),
        request_messages=sanitized,
        request_sha256=_sha256(_canonical(messages)),
        redactions=redactions,
    )
    collector.calls.append(call)
    return call


def complete_model_call(
    call: _ModelCall | None,
    *,
    response_content: str,
    usage: Mapping[str, Any] | None = None,
) -> None:
    if call is None:
        return
    redacted, redactions = _redact(response_content, max_chars=_MAX_RESPONSE_CHARS_PER_CALL)
    call.redactions.update(redactions)
    call.status = "completed"
    call.completed_at = _now()
    call.duration_ms = max(0, int((time.monotonic() - call.started_monotonic) * 1000))
    call.response_content = redacted
    call.response_sha256 = _sha256(response_content)
    call.usage = _bounded_usage(usage)


def snapshot_model_trace(collector: ModelTraceCollector | None) -> dict[str, Any] | None:
    if collector is None:
        return None
    calls: list[dict[str, Any]] = []
    for call in collector.calls:
        calls.append(
            {
                "call_id": call.call_id,
                "kind": call.kind,
                "model": call.model,
                "status": call.status,
                "started_at": call.started_at,
                "completed_at": call.completed_at,
                "duration_ms": call.duration_ms,
                "request": {
                    "messages": call.request_messages,
                    "sha256": call.request_sha256,
                },
                "response": (
                    {
                        "role": "assistant",
                        "content": call.response_content,
                        "sha256": call.response_sha256,
                    }
                    if call.response_content is not None and call.response_sha256 is not None
                    else None
                ),
                "usage": call.usage,
                "redactions": [
                    {"rule": rule, "replacements": count}
                    for rule, count in sorted(call.redactions.items())
                ],
            }
        )
    return {
        "schema_version": _SCHEMA_VERSION,
        "redacted": True,
        "calls": calls,
        "omitted_calls": collector.omitted_calls,
    }


def _sanitize_messages(
    messages: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, str]], Counter[str]]:
    output: list[dict[str, str]] = []
    redactions: Counter[str] = Counter()
    remaining = _MAX_REQUEST_CHARS_PER_CALL
    for message in messages[:_MAX_MESSAGES_PER_CALL]:
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
    if len(messages) > _MAX_MESSAGES_PER_CALL:
        redactions["message-limit"] += len(messages) - _MAX_MESSAGES_PER_CALL
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
    output, snapshot_count = _CURRENT_VIEW_SNAPSHOT.subn(
        "Current view snapshot (JSON):\n[CURRENT_VIEW_SNAPSHOT_REDACTED]",
        value,
    )
    redactions: Counter[str] = Counter()
    if snapshot_count:
        redactions["current-view-snapshot"] += snapshot_count
    for rule, pattern in _PATTERNS:
        output, count = pattern.subn(_REDACTED, output)
        if count:
            redactions[rule] += count
    if len(output) > max_chars:
        keep = max(0, max_chars - len(_TRUNCATED))
        output = f"{output[:keep]}{_TRUNCATED}"[:max_chars]
        redactions["character-limit"] += 1
    return output, redactions


def _bounded_usage(value: Mapping[str, Any] | None) -> dict[str, int] | None:
    if value is None:
        return None
    output = {
        key: item
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        if isinstance((item := value.get(key)), int) and not isinstance(item, bool) and item >= 0
    }
    return output or None


def _canonical(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError):
        return repr(value)


def _bounded_label(value: str) -> str:
    return value.strip()[:128] or "unknown"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


__all__ = [
    "ModelTraceCollector",
    "ModelTraceScope",
    "activate_model_trace",
    "begin_model_call",
    "complete_model_call",
    "deactivate_model_trace",
    "snapshot_model_trace",
]
