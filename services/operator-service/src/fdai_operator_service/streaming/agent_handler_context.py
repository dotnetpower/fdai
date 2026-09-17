"""Validate additive handler-work metadata for the Agent SSE projection.

Responsibility: accept either a complete bounded handler context or a legacy
frame with no such fields. Authority and state: pure read validation with no
write or execution authority. Deployment role: Operator Service stream helper.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Final

_MAX_FUTURE_SKEW: Final = timedelta(minutes=5)
_MAX_IDENTIFIER_CHARS: Final = 1_024
_HANDLER_PHASES: Final = frozenset({"started", "completed", "failed"})
HANDLER_ACTIVITY_FIELDS: Final = (
    "activity_id",
    "activity_correlation_id",
    "phase",
    "topic",
    "event_id",
    "event_type",
    "resource_ref",
    "resource_name",
    "resource_type",
    "started_at",
    "completed_at",
    "duration_ms",
)


def handler_activity_context(payload: Mapping[str, object]) -> dict[str, object] | None:
    """Return validated additive fields, an empty legacy context, or rejection."""
    if not any(field in payload for field in HANDLER_ACTIVITY_FIELDS):
        return {}
    activity_id = identifier(payload.get("activity_id"))
    activity_correlation_id = payload.get("activity_correlation_id")
    phase = payload.get("phase")
    topic = _text(payload.get("topic"), 512)
    event_id = payload.get("event_id")
    event_type = payload.get("event_type")
    resource_ref = payload.get("resource_ref")
    resource_name = payload.get("resource_name")
    resource_type = payload.get("resource_type")
    started_at = _aware_timestamp(payload.get("started_at"))
    completed_at = _aware_timestamp(payload.get("completed_at"))
    duration_ms = payload.get("duration_ms")
    terminal = phase in {"completed", "failed"}
    measured_duration = (
        max(0, int((completed_at - started_at).total_seconds() * 1000))
        if started_at is not None and completed_at is not None
        else None
    )
    if (
        activity_id is None
        or phase not in _HANDLER_PHASES
        or topic is None
        or (activity_correlation_id is not None and identifier(activity_correlation_id) is None)
        or (event_id is not None and identifier(event_id) is None)
        or (event_type is not None and _text(event_type, 256) is None)
        or (resource_ref is not None and identifier(resource_ref) is None)
        or (resource_name is not None and _text(resource_name, 256) is None)
        or (resource_type is not None and _text(resource_type, 256) is None)
        or started_at is None
        or (terminal != (completed_at is not None))
        or (terminal != (type(duration_ms) is int))
        or (type(duration_ms) is int and (duration_ms < 0 or duration_ms > 86_400_000))
        or (completed_at is not None and completed_at < started_at)
        or (terminal and duration_ms != measured_duration)
    ):
        return None
    return {field: payload[field] for field in HANDLER_ACTIVITY_FIELDS if field in payload}


def identifier(value: object) -> str | None:
    """Return a bounded non-empty stream identifier."""
    if not isinstance(value, str) or not value or len(value) > _MAX_IDENTIFIER_CHARS:
        return None
    return value


def _text(value: object, maximum: int) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= maximum else None


def _aware_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed > datetime.now(UTC) + _MAX_FUTURE_SKEW:
        return None
    return parsed


__all__ = ["handler_activity_context", "identifier"]
