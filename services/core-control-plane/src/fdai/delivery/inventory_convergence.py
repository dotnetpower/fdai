"""Reduce provider event, delta, and complete snapshot observations deterministically."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class InventoryObservationMode(StrEnum):
    """Limit convergence inputs to authenticated provider observation paths."""

    EVENT = "event"
    DELTA = "delta"
    SNAPSHOT = "snapshot"


class InventoryMutationKind(StrEnum):
    """Describe whether one observed identity is present or tombstoned."""

    UPSERT = "upsert"
    TOMBSTONE = "tombstone"


class InventoryConvergenceOutcome(StrEnum):
    """Explain whether one observation changed convergence state."""

    APPLIED = "applied"
    DUPLICATE = "duplicate"
    ORDERING_REJECTED = "ordering_rejected"
    SNAPSHOT_COVERED = "snapshot_covered"


@dataclass(frozen=True, slots=True)
class InventoryObservedRevision:
    """Identify one immutable provider-observed resource or relationship revision."""

    logical_key: str
    mode: InventoryObservationMode
    mutation: InventoryMutationKind
    observed_at: datetime
    recorded_at: datetime
    source_id: str
    source_revision: str
    payload_digest: str

    def __post_init__(self) -> None:
        for name in ("logical_key", "source_id", "source_revision", "payload_digest"):
            if not getattr(self, name).strip():
                raise ValueError(f"inventory observed revision {name} MUST be non-empty")
        if self.observed_at.tzinfo is None or self.recorded_at.tzinfo is None:
            raise ValueError("inventory observed revision timestamps MUST be timezone-aware")
        if self.mode is InventoryObservationMode.SNAPSHOT and (
            self.mutation is InventoryMutationKind.TOMBSTONE
        ):
            raise ValueError("snapshot absence is expressed only by a complete generation")


@dataclass(frozen=True, slots=True)
class InventoryGeneration:
    """Carry one bounded snapshot generation and its completeness authority."""

    generation_id: str
    started_at: datetime
    completed_at: datetime
    complete: bool
    revisions: tuple[InventoryObservedRevision, ...]

    def __post_init__(self) -> None:
        if not self.generation_id.strip():
            raise ValueError("inventory generation_id MUST be non-empty")
        if self.started_at.tzinfo is None or self.completed_at.tzinfo is None:
            raise ValueError("inventory generation timestamps MUST be timezone-aware")
        if self.completed_at < self.started_at:
            raise ValueError("inventory generation completion MUST NOT precede its start")
        keys: set[str] = set()
        for revision in self.revisions:
            if revision.mode is not InventoryObservationMode.SNAPSHOT:
                raise ValueError("inventory generation revisions MUST be snapshot observations")
            if revision.logical_key in keys:
                raise ValueError("inventory generation logical keys MUST be unique")
            if revision.observed_at > self.completed_at:
                raise ValueError("snapshot observation MUST NOT exceed generation completion")
            keys.add(revision.logical_key)


@dataclass(frozen=True, slots=True)
class InventoryConvergenceState:
    """Keep one complete generation plus a latest-per-key realtime overlay."""

    active_generation: InventoryGeneration | None = None
    overlay: tuple[InventoryObservedRevision, ...] = ()

    def __post_init__(self) -> None:
        keys = tuple(revision.logical_key for revision in self.overlay)
        if len(set(keys)) != len(keys):
            raise ValueError("inventory convergence overlay logical keys MUST be unique")
        if any(revision.mode is InventoryObservationMode.SNAPSHOT for revision in self.overlay):
            raise ValueError("snapshot observations MUST NOT enter the realtime overlay")

    def effective_revisions(self) -> tuple[InventoryObservedRevision, ...]:
        """Return the current graph without treating a tombstone as an observed object."""

        effective = {
            revision.logical_key: revision
            for revision in (
                self.active_generation.revisions if self.active_generation is not None else ()
            )
        }
        for revision in self.overlay:
            if revision.mutation is InventoryMutationKind.TOMBSTONE:
                effective.pop(revision.logical_key, None)
            else:
                effective[revision.logical_key] = revision
        return tuple(effective[key] for key in sorted(effective))


@dataclass(frozen=True, slots=True)
class InventoryConvergenceResult:
    """Return convergence state with a replay-stable disposition."""

    state: InventoryConvergenceState
    outcome: InventoryConvergenceOutcome


def apply_realtime_observation(
    state: InventoryConvergenceState,
    revision: InventoryObservedRevision,
) -> InventoryConvergenceResult:
    """Apply an event or delta revision without granting generation authority."""

    if revision.mode is InventoryObservationMode.SNAPSHOT:
        raise ValueError("snapshot observations require generation promotion")
    active = state.active_generation
    if active is not None and revision.observed_at <= active.started_at:
        return InventoryConvergenceResult(state, InventoryConvergenceOutcome.SNAPSHOT_COVERED)
    overlay = {item.logical_key: item for item in state.overlay}
    current = overlay.get(revision.logical_key)
    if current is not None:
        preference = compare_realtime_revisions(current, revision)
        if preference is InventoryConvergenceOutcome.DUPLICATE:
            return InventoryConvergenceResult(state, preference)
        if preference is InventoryConvergenceOutcome.ORDERING_REJECTED:
            return InventoryConvergenceResult(state, preference)
    overlay[revision.logical_key] = revision
    return InventoryConvergenceResult(
        InventoryConvergenceState(
            active_generation=active,
            overlay=tuple(overlay[key] for key in sorted(overlay)),
        ),
        InventoryConvergenceOutcome.APPLIED,
    )


def promote_inventory_generation(
    state: InventoryConvergenceState,
    generation: InventoryGeneration,
) -> InventoryConvergenceResult:
    """Atomically replace only with a complete non-regressing generation.

    Overlay observations newer than the candidate start remain authoritative realtime evidence.
    An incomplete generation cannot replace the active graph or prove any deletion.
    """

    if not generation.complete:
        return InventoryConvergenceResult(state, InventoryConvergenceOutcome.ORDERING_REJECTED)
    active = state.active_generation
    if active is not None:
        if generation.started_at < active.started_at:
            return InventoryConvergenceResult(state, InventoryConvergenceOutcome.ORDERING_REJECTED)
        if generation.generation_id == active.generation_id:
            return InventoryConvergenceResult(state, InventoryConvergenceOutcome.DUPLICATE)
    retained_overlay = tuple(
        revision for revision in state.overlay if revision.observed_at > generation.started_at
    )
    return InventoryConvergenceResult(
        InventoryConvergenceState(
            active_generation=generation,
            overlay=retained_overlay,
        ),
        InventoryConvergenceOutcome.APPLIED,
    )


def compare_realtime_revisions(
    current: InventoryObservedRevision,
    incoming: InventoryObservedRevision,
) -> InventoryConvergenceOutcome:
    """Order one logical identity by event time, tombstone, then source revision."""

    if current.logical_key != incoming.logical_key:
        raise ValueError("inventory revisions MUST address the same logical key")
    if current == incoming:
        return InventoryConvergenceOutcome.DUPLICATE
    if incoming.observed_at < current.observed_at:
        return InventoryConvergenceOutcome.ORDERING_REJECTED
    if incoming.observed_at > current.observed_at:
        return InventoryConvergenceOutcome.APPLIED
    if current.mutation is not incoming.mutation:
        return (
            InventoryConvergenceOutcome.APPLIED
            if incoming.mutation is InventoryMutationKind.TOMBSTONE
            else InventoryConvergenceOutcome.ORDERING_REJECTED
        )
    return (
        InventoryConvergenceOutcome.APPLIED
        if incoming.source_revision > current.source_revision
        else InventoryConvergenceOutcome.ORDERING_REJECTED
    )


__all__ = [
    "InventoryConvergenceOutcome",
    "InventoryConvergenceResult",
    "InventoryConvergenceState",
    "InventoryGeneration",
    "InventoryMutationKind",
    "InventoryObservationMode",
    "InventoryObservedRevision",
    "apply_realtime_observation",
    "compare_realtime_revisions",
    "promote_inventory_generation",
]
