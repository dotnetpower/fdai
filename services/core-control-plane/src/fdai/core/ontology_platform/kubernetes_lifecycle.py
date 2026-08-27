"""Typed durable Kubernetes lifecycle observations and cursor state."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

_MAX_TEXT = 512


def _bounded(name: str, value: str, *, maximum: int = _MAX_TEXT) -> None:
    if not value.strip() or len(value) > maximum:
        raise ValueError(f"Kubernetes lifecycle {name} MUST be bounded non-empty text")


@dataclass(frozen=True, slots=True)
class KubernetesLifecycleObservation:
    """One append-only Event revision without provider-controlled message text."""

    observation_id: str
    cluster_ref: str
    event_uid: str
    object_uid: str
    object_kind: str
    namespace: str | None
    owner_uid: str | None
    reason: str
    event_type: str
    lifecycle_kind: str
    action: str
    occurred_at: datetime
    recorded_at: datetime
    source_revision: str
    occurrence_count: int
    evidence_ref: str

    def __post_init__(self) -> None:
        for name, value in (
            ("observation_id", self.observation_id),
            ("cluster_ref", self.cluster_ref),
            ("event_uid", self.event_uid),
            ("object_uid", self.object_uid),
            ("object_kind", self.object_kind),
            ("reason", self.reason),
            ("event_type", self.event_type),
            ("lifecycle_kind", self.lifecycle_kind),
            ("action", self.action),
            ("source_revision", self.source_revision),
            ("evidence_ref", self.evidence_ref),
        ):
            _bounded(name, value)
        for name, optional_value in (("namespace", self.namespace), ("owner_uid", self.owner_uid)):
            if optional_value is not None:
                _bounded(name, optional_value)
        if self.occurred_at.tzinfo is None or self.recorded_at.tzinfo is None:
            raise ValueError("Kubernetes lifecycle times MUST be timezone-aware")
        if self.recorded_at < self.occurred_at:
            raise ValueError("Kubernetes lifecycle recorded_at MUST follow occurred_at")
        if self.occurrence_count < 1:
            raise ValueError("Kubernetes lifecycle occurrence_count MUST be positive")


@dataclass(frozen=True, slots=True)
class KubernetesLifecycleCursor:
    """One locally monotonic checkpoint with an opaque provider resume token."""

    cluster_ref: str
    sequence: int
    resume_token: str | None
    coverage_started_at: datetime
    coverage_through_at: datetime
    retention_floor_at: datetime
    limitation: str | None

    def __post_init__(self) -> None:
        _bounded("cluster_ref", self.cluster_ref)
        if self.sequence < 0:
            raise ValueError("Kubernetes lifecycle sequence MUST be non-negative")
        if self.resume_token is not None:
            _bounded("resume_token", self.resume_token, maximum=1024)
        for value in (
            self.coverage_started_at,
            self.coverage_through_at,
            self.retention_floor_at,
        ):
            if value.tzinfo is None:
                raise ValueError("Kubernetes lifecycle cursor times MUST be timezone-aware")
        if self.coverage_through_at < self.coverage_started_at:
            raise ValueError("Kubernetes lifecycle coverage cannot move backward")
        if self.retention_floor_at < self.coverage_started_at:
            raise ValueError("Kubernetes lifecycle retention floor precedes coverage")
        if self.limitation is not None:
            _bounded("limitation", self.limitation, maximum=128)


@dataclass(frozen=True, slots=True)
class KubernetesLifecycleBatch:
    """One bounded watch result committed atomically with its next checkpoint."""

    cluster_ref: str
    expected_sequence: int
    next_resume_token: str | None
    coverage_started_at: datetime
    coverage_through_at: datetime
    observations: tuple[KubernetesLifecycleObservation, ...]
    limitation: str | None

    def __post_init__(self) -> None:
        _bounded("cluster_ref", self.cluster_ref)
        if self.expected_sequence < 0:
            raise ValueError("Kubernetes lifecycle expected_sequence MUST be non-negative")
        if self.next_resume_token is not None:
            _bounded("next_resume_token", self.next_resume_token, maximum=1024)
        if self.coverage_started_at.tzinfo is None or self.coverage_through_at.tzinfo is None:
            raise ValueError("Kubernetes lifecycle batch times MUST be timezone-aware")
        if self.coverage_through_at < self.coverage_started_at:
            raise ValueError("Kubernetes lifecycle batch coverage cannot move backward")
        identities = tuple(item.observation_id for item in self.observations)
        if identities != tuple(sorted(set(identities))):
            raise ValueError("Kubernetes lifecycle observations MUST be unique and ordered")
        if any(item.cluster_ref != self.cluster_ref for item in self.observations):
            raise ValueError("Kubernetes lifecycle batch widened cluster scope")
        if self.limitation is not None:
            _bounded("limitation", self.limitation, maximum=128)


def lifecycle_digest(*parts: str) -> str:
    """Return a replay-stable content identity without exposing source text."""

    return f"sha256:{hashlib.sha256(chr(31).join(parts).encode()).hexdigest()}"


def advance_lifecycle_cursor(
    cursor: KubernetesLifecycleCursor,
    batch: KubernetesLifecycleBatch,
) -> KubernetesLifecycleCursor | None:
    """Advance only the expected local sequence and never compare provider tokens."""

    if batch.cluster_ref != cursor.cluster_ref or batch.expected_sequence != cursor.sequence:
        return None
    if batch.coverage_through_at < cursor.coverage_through_at:
        return None
    return KubernetesLifecycleCursor(
        cluster_ref=cursor.cluster_ref,
        sequence=cursor.sequence + 1,
        resume_token=batch.next_resume_token,
        coverage_started_at=max(cursor.coverage_started_at, batch.coverage_started_at),
        coverage_through_at=batch.coverage_through_at,
        retention_floor_at=max(cursor.retention_floor_at, batch.coverage_started_at),
        limitation=batch.limitation,
    )


__all__ = [
    "KubernetesLifecycleBatch",
    "KubernetesLifecycleCursor",
    "KubernetesLifecycleObservation",
    "advance_lifecycle_cursor",
    "lifecycle_digest",
]
