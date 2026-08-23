"""Convergence tests for event, delta, snapshot, and tombstone authority."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import permutations

import pytest
from fdai.delivery.inventory_convergence import (
    InventoryConvergenceOutcome,
    InventoryConvergenceState,
    InventoryGeneration,
    InventoryMutationKind,
    InventoryObservationMode,
    InventoryObservedRevision,
    apply_realtime_observation,
    promote_inventory_generation,
)

_START = datetime(2026, 8, 22, 1, 0, tzinfo=UTC)


def _revision(
    key: str,
    *,
    mode: InventoryObservationMode,
    seconds: int,
    source_revision: str,
    mutation: InventoryMutationKind = InventoryMutationKind.UPSERT,
) -> InventoryObservedRevision:
    return InventoryObservedRevision(
        logical_key=key,
        mode=mode,
        mutation=mutation,
        observed_at=_START + timedelta(seconds=seconds),
        recorded_at=_START + timedelta(seconds=seconds + 1),
        source_id=f"provider-{mode.value}",
        source_revision=source_revision,
        payload_digest=f"sha256:{source_revision}",
    )


def _generation(
    generation_id: str,
    *,
    started_seconds: int,
    keys: tuple[str, ...],
    complete: bool = True,
) -> InventoryGeneration:
    return InventoryGeneration(
        generation_id=generation_id,
        started_at=_START + timedelta(seconds=started_seconds),
        completed_at=_START + timedelta(seconds=started_seconds + 10),
        complete=complete,
        revisions=tuple(
            _revision(
                key,
                mode=InventoryObservationMode.SNAPSHOT,
                seconds=started_seconds + 5,
                source_revision=f"{generation_id}-{index}",
            )
            for index, key in enumerate(keys)
        ),
    )


def _effective_identity(state: InventoryConvergenceState) -> tuple[tuple[str, str], ...]:
    return tuple(
        (revision.logical_key, revision.source_revision) for revision in state.effective_revisions()
    )


def test_event_and_delta_duplicates_and_reordering_converge() -> None:
    generation = _generation("generation-1", started_seconds=0, keys=("resource:a",))
    base = promote_inventory_generation(InventoryConvergenceState(), generation).state
    changes = (
        _revision(
            "resource:a",
            mode=InventoryObservationMode.EVENT,
            seconds=20,
            source_revision="event-1",
        ),
        _revision(
            "resource:a",
            mode=InventoryObservationMode.DELTA,
            seconds=30,
            source_revision="delta-2",
        ),
        _revision(
            "resource:a",
            mode=InventoryObservationMode.DELTA,
            seconds=30,
            source_revision="delta-2",
        ),
    )

    results: set[tuple[tuple[str, str], ...]] = set()
    for ordering in permutations(changes):
        state = base
        for revision in ordering:
            state = apply_realtime_observation(state, revision).state
        results.add(_effective_identity(state))

    assert results == {(("resource:a", "delta-2"),)}


def test_tombstone_wins_equal_time_and_cannot_be_resurrected_by_older_delta() -> None:
    state = promote_inventory_generation(
        InventoryConvergenceState(),
        _generation("generation-1", started_seconds=0, keys=("resource:a", "link:a-b")),
    ).state
    delete = _revision(
        "resource:a",
        mode=InventoryObservationMode.EVENT,
        seconds=20,
        source_revision="event-a",
        mutation=InventoryMutationKind.TOMBSTONE,
    )
    same_time_upsert = _revision(
        "resource:a",
        mode=InventoryObservationMode.DELTA,
        seconds=20,
        source_revision="event-z",
    )
    old_link_delete = _revision(
        "link:a-b",
        mode=InventoryObservationMode.EVENT,
        seconds=20,
        source_revision="event-link-delete",
        mutation=InventoryMutationKind.TOMBSTONE,
    )

    state = apply_realtime_observation(state, delete).state
    rejected = apply_realtime_observation(state, same_time_upsert)
    state = apply_realtime_observation(rejected.state, old_link_delete).state

    assert rejected.outcome is InventoryConvergenceOutcome.ORDERING_REJECTED
    assert state.effective_revisions() == ()
    assert {item.logical_key for item in state.overlay} == {"resource:a", "link:a-b"}


def test_complete_snapshot_replaces_generation_but_retains_newer_overlay() -> None:
    first = _generation("generation-1", started_seconds=0, keys=("resource:a", "resource:b"))
    state = promote_inventory_generation(InventoryConvergenceState(), first).state
    covered_event = _revision(
        "resource:a",
        mode=InventoryObservationMode.EVENT,
        seconds=20,
        source_revision="event-covered",
    )
    newer_delta = _revision(
        "resource:c",
        mode=InventoryObservationMode.DELTA,
        seconds=40,
        source_revision="delta-retained",
    )
    state = apply_realtime_observation(state, covered_event).state
    state = apply_realtime_observation(state, newer_delta).state

    second = _generation("generation-2", started_seconds=30, keys=("resource:a",))
    result = promote_inventory_generation(state, second)

    assert result.outcome is InventoryConvergenceOutcome.APPLIED
    assert _effective_identity(result.state) == (
        ("resource:a", "generation-2-0"),
        ("resource:c", "delta-retained"),
    )
    assert tuple(item.logical_key for item in result.state.overlay) == ("resource:c",)


def test_partial_snapshot_cannot_replace_or_prove_deletion() -> None:
    first = _generation("generation-1", started_seconds=0, keys=("resource:a", "resource:b"))
    state = promote_inventory_generation(InventoryConvergenceState(), first).state
    partial = _generation(
        "generation-partial",
        started_seconds=30,
        keys=("resource:a",),
        complete=False,
    )

    result = promote_inventory_generation(state, partial)

    assert result.outcome is InventoryConvergenceOutcome.ORDERING_REJECTED
    assert result.state is state
    assert {item.logical_key for item in result.state.effective_revisions()} == {
        "resource:a",
        "resource:b",
    }


def test_concurrent_promotions_converge_on_newest_complete_generation() -> None:
    older = _generation("generation-older", started_seconds=10, keys=("resource:a",))
    newer = _generation("generation-newer", started_seconds=20, keys=("resource:b",))

    older_then_newer = promote_inventory_generation(
        promote_inventory_generation(InventoryConvergenceState(), older).state,
        newer,
    )
    newer_then_older = promote_inventory_generation(
        promote_inventory_generation(InventoryConvergenceState(), newer).state,
        older,
    )

    assert older_then_newer.state.active_generation == newer
    assert newer_then_older.state.active_generation == newer
    assert newer_then_older.outcome is InventoryConvergenceOutcome.ORDERING_REJECTED


def test_snapshot_tombstone_is_rejected_because_absence_needs_complete_coverage() -> None:
    with pytest.raises(ValueError, match="complete generation"):
        _revision(
            "resource:a",
            mode=InventoryObservationMode.SNAPSHOT,
            seconds=5,
            source_revision="snapshot-delete",
            mutation=InventoryMutationKind.TOMBSTONE,
        )
