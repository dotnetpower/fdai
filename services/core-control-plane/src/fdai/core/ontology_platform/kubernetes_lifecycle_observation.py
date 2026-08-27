"""Typed Kubernetes lifecycle observation retained by durable resumable ingestion.

Collectors append these observations only; they never mutate ontology instances.
Normalization keys exclusively on the bounded Kubernetes Event `reason` token, never on
free-form `message` text, so category identity cannot depend on provider prose.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

KUBERNETES_LIFECYCLE_KILLING: Final = "killing"
KUBERNETES_LIFECYCLE_FAILED: Final = "failed"
KUBERNETES_LIFECYCLE_BACKOFF: Final = "backoff"
KUBERNETES_LIFECYCLE_UNHEALTHY: Final = "unhealthy"
KUBERNETES_LIFECYCLE_SUCCESSFUL_CREATE: Final = "successful_create"
KUBERNETES_LIFECYCLE_SCHEDULED: Final = "scheduled"
KUBERNETES_LIFECYCLE_STARTED: Final = "started"
KUBERNETES_LIFECYCLE_DELETION: Final = "deletion"
KUBERNETES_LIFECYCLE_OTHER: Final = "other"

# Reason tokens are structured Kubernetes machine identifiers (never the free-form
# `message` field). Keys are pre-normalized to lowercase alphanumeric-only form so the
# lookup is resilient to `BackOff` vs `Backoff` style provider variance.
_REASON_CATEGORY_MAP: Final[dict[str, str]] = {
    "killing": KUBERNETES_LIFECYCLE_KILLING,
    "failed": KUBERNETES_LIFECYCLE_FAILED,
    "backoff": KUBERNETES_LIFECYCLE_BACKOFF,
    "unhealthy": KUBERNETES_LIFECYCLE_UNHEALTHY,
    "successfulcreate": KUBERNETES_LIFECYCLE_SUCCESSFUL_CREATE,
    "scheduled": KUBERNETES_LIFECYCLE_SCHEDULED,
    "started": KUBERNETES_LIFECYCLE_STARTED,
    "successfuldelete": KUBERNETES_LIFECYCLE_DELETION,
    "faileddelete": KUBERNETES_LIFECYCLE_DELETION,
    "deleted": KUBERNETES_LIFECYCLE_DELETION,
}

KUBERNETES_LIFECYCLE_CATEGORIES: Final[frozenset[str]] = frozenset(
    {*_REASON_CATEGORY_MAP.values(), KUBERNETES_LIFECYCLE_OTHER}
)


def normalize_kubernetes_lifecycle_reason(reason: str) -> str:
    """Return the fixed lifecycle category for one bounded Event `reason` token.

    Identity is derived exclusively from `reason`; the human-readable `message` field
    MUST NOT be consulted here, matching the no-message-text-identity invariant.
    """

    key = "".join(character for character in reason.strip().casefold() if character.isalnum())
    return _REASON_CATEGORY_MAP.get(key, KUBERNETES_LIFECYCLE_OTHER)


@dataclass(frozen=True, slots=True)
class KubernetesLifecycleObservation:
    """One append-only Kubernetes lifecycle observation bound to an exact object UID."""

    cluster_ref: str
    namespace: str | None
    object_uid: str
    owner_uid: str | None
    reason: str
    category: str
    event_type: str
    event_time: datetime
    recorded_time: datetime
    source_revision: str
    evidence_ref: str

    def __post_init__(self) -> None:
        for name, value, maximum in (
            ("cluster_ref", self.cluster_ref, 512),
            ("object_uid", self.object_uid, 512),
            ("reason", self.reason, 128),
            ("event_type", self.event_type, 64),
            ("source_revision", self.source_revision, 128),
            ("evidence_ref", self.evidence_ref, 256),
        ):
            if not value.strip() or len(value) > maximum:
                raise ValueError(f"Kubernetes lifecycle {name} MUST be bounded and non-empty")
        if self.namespace is not None and (not self.namespace.strip() or len(self.namespace) > 253):
            raise ValueError("Kubernetes lifecycle namespace MUST be bounded when present")
        if self.owner_uid is not None and (not self.owner_uid.strip() or len(self.owner_uid) > 512):
            raise ValueError("Kubernetes lifecycle owner_uid MUST be bounded when present")
        if self.category not in KUBERNETES_LIFECYCLE_CATEGORIES:
            raise ValueError("Kubernetes lifecycle category is not recognized")
        if self.event_time.tzinfo is None or self.recorded_time.tzinfo is None:
            raise ValueError("Kubernetes lifecycle observation times MUST be timezone-aware")


__all__ = [
    "KUBERNETES_LIFECYCLE_BACKOFF",
    "KUBERNETES_LIFECYCLE_CATEGORIES",
    "KUBERNETES_LIFECYCLE_DELETION",
    "KUBERNETES_LIFECYCLE_FAILED",
    "KUBERNETES_LIFECYCLE_KILLING",
    "KUBERNETES_LIFECYCLE_OTHER",
    "KUBERNETES_LIFECYCLE_SCHEDULED",
    "KUBERNETES_LIFECYCLE_STARTED",
    "KUBERNETES_LIFECYCLE_SUCCESSFUL_CREATE",
    "KUBERNETES_LIFECYCLE_UNHEALTHY",
    "KubernetesLifecycleObservation",
    "normalize_kubernetes_lifecycle_reason",
]
