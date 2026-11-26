"""Projection results and checkpoint state for inventory ontology refreshes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class InventoryOntologyProjectionStatus(StrEnum):
    """Availability of the latest promoted inventory projection attempt."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class InventoryOntologyProjectionResult:
    """Counts and coverage for one applied generation."""

    generation: str
    ontology_release_digest: str
    status: InventoryOntologyProjectionStatus
    object_count: int
    link_count: int
    complete: bool
    relationship_complete: bool
    dropped_reasons: tuple[str, ...]
    journal_high_watermark: int | None = None
    projection_high_watermark: int | None = None


@dataclass(frozen=True, slots=True)
class InventoryProjectionCheckpoints:
    """Keep global retention and active-scope graph checkpoints distinct."""

    journal_high_watermark: int | None
    projection_high_watermark: int | None
    active_scope_projection_watermark: int | None
    active_scope_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if (self.journal_high_watermark is None) != (self.projection_high_watermark is None):
            raise ValueError("inventory ontology journal watermarks MUST be supplied together")
        if (self.active_scope_projection_watermark is None) != (not self.active_scope_refs):
            raise ValueError(
                "inventory ontology active-scope checkpoint and scopes MUST be supplied together"
            )
        if (
            self.journal_high_watermark is not None
            and self.projection_high_watermark is not None
            and self.projection_high_watermark > self.journal_high_watermark
        ):
            raise ValueError("inventory ontology projection watermark exceeds journal")
        if self.active_scope_projection_watermark is not None and (
            self.journal_high_watermark is None
            or self.active_scope_projection_watermark > self.journal_high_watermark
        ):
            raise ValueError("inventory ontology active-scope checkpoint exceeds journal")
        if self.active_scope_refs != tuple(sorted(set(self.active_scope_refs))):
            raise ValueError("inventory ontology active scopes MUST be unique and ordered")

    def active_scope_state(self, *, generation: str) -> dict[str, object] | None:
        """Return the durable active-scope checkpoint, when one was supplied."""

        if self.active_scope_projection_watermark is None:
            return None
        return {
            "schema_version": "1.0.0",
            "generation": generation,
            "scope_refs": list(self.active_scope_refs),
            "journal_high_watermark": self.journal_high_watermark,
            "projection_high_watermark": self.active_scope_projection_watermark,
        }


__all__ = [
    "InventoryOntologyProjectionResult",
    "InventoryOntologyProjectionStatus",
    "InventoryProjectionCheckpoints",
]
