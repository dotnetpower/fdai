"""Typed Kubernetes Pod termination evidence shared by Pod reducers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

_MAX_ID_LENGTH = 512
_TERMINATION_UNAVAILABLE_REASONS = frozenset(
    {
        "authorization_denied",
        "cursor_expired",
        "durable_history_unavailable",
        "resource_event_response_invalid",
        "result_limit",
        "source_retention_incomplete",
        "source_retention_stale",
        "source_scope_incomplete",
        "source_unavailable",
    }
)
PodTerminationUnavailableReason = Literal[
    "authorization_denied",
    "cursor_expired",
    "durable_history_unavailable",
    "resource_event_response_invalid",
    "result_limit",
    "source_retention_incomplete",
    "source_retention_stale",
    "source_scope_incomplete",
    "source_unavailable",
]


@dataclass(frozen=True, slots=True)
class PodTerminationObservation:
    """One retained termination observation for an immutable Pod UID."""

    pod_uid: str
    cluster_id: str
    namespace: str
    event_type: str | None
    reason: str | None
    exit_code: int | None
    signal: int | None
    finished_at: datetime | None
    event_time: datetime | None
    recorded_at: datetime | None
    source_identity: str | None
    source_revision: str | None
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("pod_uid", "cluster_id", "namespace"):
            value = getattr(self, field_name)
            if not value.strip() or len(value) > _MAX_ID_LENGTH:
                raise ValueError(f"termination {field_name} MUST be bounded non-empty text")
        for field_name in ("finished_at", "event_time", "recorded_at"):
            value = getattr(self, field_name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"termination {field_name} MUST be timezone-aware")
        for field_name in ("exit_code", "signal"):
            value = getattr(self, field_name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"termination {field_name} MUST be a non-negative integer or null")
        for field_name in ("source_identity", "source_revision"):
            value = getattr(self, field_name)
            if value is not None and (not value.strip() or len(value) > _MAX_ID_LENGTH):
                raise ValueError(f"termination {field_name} MUST be bounded non-empty text or null")
        if not self.evidence_refs or any(not item for item in self.evidence_refs):
            raise ValueError("termination observation MUST cite evidence")


def is_termination_unavailable_reason(value: object) -> bool:
    """Return whether ``value`` is one reviewed termination source limitation."""

    return value in _TERMINATION_UNAVAILABLE_REASONS


def termination_unavailable_gap(reason: PodTerminationUnavailableReason) -> str:
    """Return the replacement reducer gap for one reviewed lifecycle limitation."""

    return f"termination_kubernetes_lifecycle_{reason}"


__all__ = [
    "PodTerminationObservation",
    "PodTerminationUnavailableReason",
    "is_termination_unavailable_reason",
    "termination_unavailable_gap",
]
