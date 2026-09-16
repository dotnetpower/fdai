"""Immutable records shared by the inventory synchronization coordinator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from fdai.shared.providers.inventory import LinkRecord, RelationshipDrop, ResourceRecord


@dataclass(frozen=True, slots=True)
class PromotedInventoryObservation:
    """One promoted snapshot handed to a derived read model.

    ``generation`` is the promoted snapshot identity. ``complete`` is ``False``
    when accumulation hit its ceiling, so a consumer cannot read absence from a
    truncated observation.
    """

    generation: str
    resources: tuple[ResourceRecord, ...]
    links: tuple[LinkRecord, ...]
    complete: bool
    relationship_drops: tuple[RelationshipDrop, ...] = ()
    recorded_at: datetime | None = None
    source_states: tuple[InventoryProjectionSourceState, ...] = ()
    state_base_generation: str | None = None
    state_base_generation_checked: bool = False


class InventoryProjectionSourceStatus(StrEnum):
    """Availability of one independently collected projection source."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class InventoryProjectionSourceState:
    """Principal-safe source state retained with one promoted generation."""

    source: str
    status: InventoryProjectionSourceStatus
    observed_at: datetime | None
    reason: str | None
    scope_digest: str | None = None
    coverage: Mapping[str, int] = field(default_factory=dict)
    additive: bool = False

    def __post_init__(self) -> None:
        if not self.source.strip() or len(self.source) > 128:
            raise ValueError("inventory projection source MUST be bounded non-empty text")
        if self.scope_digest is not None and (
            not self.scope_digest.startswith("sha256:")
            or len(self.scope_digest) != 71
            or any(character not in "0123456789abcdef" for character in self.scope_digest[7:])
        ):
            raise ValueError("inventory projection source scope_digest MUST be lowercase SHA-256")
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            raise ValueError("inventory projection source observed_at MUST be timezone-aware")
        if self.status is InventoryProjectionSourceStatus.AVAILABLE:
            if self.observed_at is None or self.reason is not None:
                raise ValueError("available inventory projection source MUST have only observed_at")
        elif self.observed_at is not None or not self.reason or len(self.reason) > 128:
            raise ValueError("unavailable inventory projection source MUST have only a reason")
        if any(
            not isinstance(key, str) or not isinstance(value, int) or value < 0
            for key, value in self.coverage.items()
        ):
            raise ValueError("inventory projection source coverage MUST contain counts")
        if not isinstance(self.additive, bool):
            raise ValueError("inventory projection source additive flag MUST be boolean")

    def to_metadata(self) -> dict[str, object]:
        """Return a sanitized generation metadata record."""

        metadata: dict[str, object] = {
            "source": self.source,
            "status": self.status.value,
            "observed_at": self.observed_at.isoformat() if self.observed_at is not None else None,
            "reason": self.reason,
        }
        if self.coverage:
            metadata["coverage"] = dict(sorted(self.coverage.items()))
        if self.scope_digest is not None:
            metadata["scope_digest"] = self.scope_digest
        return metadata


@dataclass(frozen=True, slots=True)
class InventoryRelationshipCoverage:
    """Exact counted disposition of every candidate ontology relationship instance."""

    materialized: int
    reviewed_unavailable: int
    unclassified: int
    total_candidates: int
    complete: bool

    def __post_init__(self) -> None:
        for field_name, value in (
            ("materialized", self.materialized),
            ("reviewed_unavailable", self.reviewed_unavailable),
            ("unclassified", self.unclassified),
            ("total_candidates", self.total_candidates),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(
                    f"inventory relationship coverage {field_name} MUST be a non-negative count"
                )
        if self.total_candidates != (
            self.materialized + self.reviewed_unavailable + self.unclassified
        ):
            raise ValueError(
                "inventory relationship coverage total_candidates MUST equal its counted parts"
            )
        if self.complete and self.unclassified != 0:
            raise ValueError(
                "inventory relationship coverage complete MUST be false with unclassified drops"
            )

    def to_metadata(self) -> dict[str, object]:
        """Return the sanitized generation metadata record for this coverage."""

        return {
            "total_candidates": self.total_candidates,
            "materialized": self.materialized,
            "reviewed_unavailable": self.reviewed_unavailable,
            "unclassified": self.unclassified,
            "complete": self.complete,
        }


def compute_relationship_coverage(
    observation: PromotedInventoryObservation,
) -> InventoryRelationshipCoverage:
    """Count every candidate relationship instance in one promoted observation."""

    materialized = len(observation.links)
    reviewed_unavailable = sum(
        1 for drop in observation.relationship_drops if drop.unavailable_reason is not None
    )
    unclassified = sum(
        1 for drop in observation.relationship_drops if drop.unavailable_reason is None
    )
    return InventoryRelationshipCoverage(
        materialized=materialized,
        reviewed_unavailable=reviewed_unavailable,
        unclassified=unclassified,
        total_candidates=materialized + reviewed_unavailable + unclassified,
        complete=unclassified == 0 and observation.complete,
    )


__all__ = [
    "InventoryProjectionSourceState",
    "InventoryProjectionSourceStatus",
    "InventoryRelationshipCoverage",
    "PromotedInventoryObservation",
    "compute_relationship_coverage",
]
