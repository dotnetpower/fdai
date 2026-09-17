"""Build privacy-bounded metadata for observed Pantheon handler work.

Responsibility: derive one stable, authority-free activity identity and bounded
resource context from an already accepted runtime payload. Dependencies: only
standard-library hashing and timestamp parsing. Deployment role: pure helper
used by Core activity publication; it performs no I/O or durable write.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

MAX_IDENTIFIER_CHARS = 1_024


@dataclass(frozen=True, slots=True)
class HandlerActivityContext:
    """Bounded fields that identify and describe one handler invocation."""

    activity_id: str
    activity_correlation_id: str | None
    phase: str
    topic: str
    event_id: str | None
    event_type: str | None
    resource_ref: str | None
    resource_name: str | None
    resource_type: str | None
    started_at: str
    completed_at: str | None
    duration_ms: int | None

    def to_payload(self) -> dict[str, object]:
        """Return additive flattened fields for the runtime-state payload."""
        return {
            key: value
            for key, value in {
                "activity_id": self.activity_id,
                "activity_correlation_id": self.activity_correlation_id,
                "phase": self.phase,
                "topic": self.topic,
                "event_id": self.event_id,
                "event_type": self.event_type,
                "resource_ref": self.resource_ref,
                "resource_name": self.resource_name,
                "resource_type": self.resource_type,
                "started_at": self.started_at,
                "completed_at": self.completed_at,
                "duration_ms": self.duration_ms,
            }.items()
            if value is not None
        }


def handler_activity_context(
    *,
    agent: str,
    topic: str,
    phase: str,
    payload: Mapping[str, object],
    transition_at: str,
    started_at: str | None,
) -> HandlerActivityContext | None:
    """Return structured context only when the invocation has stable identity."""
    identity = first_bounded_identifier(
        payload,
        "idempotency_key",
        "event_id",
        "correlation_id",
    )
    if identity is None:
        return None
    digest = hashlib.sha256(f"{agent}\0{topic}\0{identity}".encode()).hexdigest()
    activity_started_at = transition_at if phase == "started" else started_at
    if activity_started_at is None:
        return None
    completed_at = None if phase == "started" else transition_at
    resource_ref = first_bounded_identifier(
        payload,
        "resource_ref",
        "target_resource_ref",
        "resource_id",
    )
    return HandlerActivityContext(
        activity_id=f"handler:{digest[:32]}",
        activity_correlation_id=bounded_identifier(payload.get("correlation_id")),
        phase=phase,
        topic=topic,
        event_id=bounded_identifier(payload.get("event_id")),
        event_type=bounded_text(payload.get("event_type"), 256),
        resource_ref=resource_ref,
        resource_name=_resource_name(payload.get("resource_name"), resource_ref),
        resource_type=bounded_text(payload.get("resource_type"), 256),
        started_at=activity_started_at,
        completed_at=completed_at,
        duration_ms=_duration_ms(activity_started_at, completed_at),
    )


def first_bounded_identifier(
    payload: Mapping[str, object],
    *keys: str,
) -> str | None:
    """Return the first present bounded identifier from the ordered keys."""
    for key in keys:
        value = bounded_identifier(payload.get(key))
        if value is not None:
            return value
    return None


def bounded_identifier(value: object) -> str | None:
    """Return one non-empty identifier within the shared runtime bound."""
    if not isinstance(value, str) or not value or len(value) > MAX_IDENTIFIER_CHARS:
        return None
    return value


def bounded_text(value: object, maximum: int) -> str | None:
    """Return trimmed bounded presentation text or no value."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    return candidate if candidate and len(candidate) <= maximum else None


def _resource_name(value: object, resource_ref: str | None) -> str | None:
    recorded = bounded_text(value, 256)
    if recorded is not None:
        return recorded
    if resource_ref is None:
        return None
    return bounded_text(resource_ref.rsplit("/", 1)[-1], 256)


def _duration_ms(started_at: str, completed_at: str | None) -> int | None:
    if completed_at is None:
        return None
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        completed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, int((completed - started).total_seconds() * 1000))


__all__ = ["HandlerActivityContext", "bounded_identifier", "handler_activity_context"]
