"""Server-Sent Events frame serialization for read API streams."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fdai.shared.providers.sse import SseEvent

_MAX_SSE_FIELD_CHARS = 8192
"""Length cap for a single ``id:`` or ``event:`` line."""

_MAX_SSE_DATA_CHARS = 256 * 1024
"""Character cap for one event's ``data`` payload."""


def encode_sse_frame(payload: Mapping[str, Any], *, kind: str = "control") -> bytes:
    """Encode one mapping as a complete SSE frame."""
    body = json.dumps(payload, separators=(",", ":"))
    name = _sse_field(kind) or "message"
    lines = [f"event: {name}", *_sse_data_lines(body)]
    return ("\n".join(lines) + "\n\n").encode()


def encode_sse_event(event: SseEvent) -> bytes:
    """Encode one event while preventing SSE field and frame injection."""
    parts: list[str] = []
    if event.id:
        field = _sse_field(event.id)
        if field:
            parts.append(f"id: {field}")
    parts.append(f"event: {_sse_field(event.event) or 'message'}")
    parts.extend(_sse_data_lines(event.data))
    if event.retry_ms is not None and event.retry_ms >= 0:
        parts.append(f"retry: {int(event.retry_ms)}")
    return ("\n".join(parts) + "\n\n").encode()


def _sse_field(value: str) -> str:
    """Flatten and cap an ``id`` or ``event`` field value."""
    flattened = value.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").strip()
    if len(flattened) > _MAX_SSE_FIELD_CHARS:
        flattened = flattened[:_MAX_SSE_FIELD_CHARS]
    return flattened


def _sse_data_lines(data: str) -> list[str]:
    """Render data as spec-correct lines after normalizing line endings."""
    capped = data if len(data) <= _MAX_SSE_DATA_CHARS else data[:_MAX_SSE_DATA_CHARS]
    normalized = capped.replace("\r\n", "\n").replace("\r", "\n")
    return [f"data: {line}" for line in normalized.split("\n")]


def iso_ts_utc() -> str:
    """Return a millisecond-precision UTC timestamp with a trailing Z."""
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


__all__ = [
    "_MAX_SSE_DATA_CHARS",
    "_MAX_SSE_FIELD_CHARS",
    "encode_sse_event",
    "encode_sse_frame",
    "iso_ts_utc",
]
