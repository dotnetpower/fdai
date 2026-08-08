"""Operational state trajectory and Dynamic closure tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fdai.core.assurance_twin import (
    DynamicInvariant,
    InvariantOperator,
    InvariantStatus,
    OperationalStateTrajectory,
    StateSlice,
    TrajectoryKind,
    TrajectoryOutcomeStatus,
    close_trajectory_outcome,
    evaluate_dynamic_invariants,
)

_NOW = datetime(2026, 8, 4, tzinfo=UTC)


def _slices(
    *,
    observed: bool = False,
    second_value: float = 80.0,
) -> tuple[StateSlice, ...]:
    evidence = ("metric:example",) if observed else ()
    model_ref = None if observed else "graph-effect:latency@1.0.0"
    return (
        StateSlice(
            object_ref="resource:api",
            object_type="Resource",
            metric="latency_p99_ms",
            value=50.0,
            effective_at=_NOW,
            evidence_refs=evidence,
            model_ref=model_ref,
            independent_observer=observed,
        ),
        StateSlice(
            object_ref="resource:api",
            object_type="Resource",
            metric="latency_p99_ms",
            value=second_value,
            effective_at=_NOW + timedelta(minutes=1),
            evidence_refs=evidence,
            model_ref=model_ref,
            independent_observer=observed,
        ),
    )


def _trajectory(
    kind: TrajectoryKind,
    *,
    second_value: float = 80.0,
    complete: bool = True,
    truncated: bool = False,
    censoring_refs: tuple[str, ...] = (),
) -> OperationalStateTrajectory:
    return OperationalStateTrajectory(
        kind=kind,
        ontology_release="sha256:" + "a" * 64,
        graph_revision="graph-7",
        inventory_generation="inventory-4",
        base_snapshot_id="snapshot-2",
        evidence_cutoff=_NOW,
        horizon_end=_NOW + timedelta(minutes=2),
        slices=_slices(
            observed=kind is TrajectoryKind.OBSERVED,
            second_value=second_value,
        ),
        intervention_refs=("action:scale",),
        censoring_refs=censoring_refs,
        source_watermarks=("metrics:42",),
        complete=complete,
        truncated=truncated,
        truncation_reasons=("source_limit",) if truncated else (),
    )


def test_trajectory_digest_is_order_and_timezone_stable() -> None:
    baseline = _trajectory(TrajectoryKind.PREDICTED)
    offset = timezone(timedelta(hours=9))
    shifted = replace(
        baseline,
        evidence_cutoff=baseline.evidence_cutoff.astimezone(offset),
        horizon_end=baseline.horizon_end.astimezone(offset),
        slices=tuple(
            replace(item, effective_at=item.effective_at.astimezone(offset))
            for item in baseline.slices
        ),
    )

    assert baseline.digest == shifted.digest


def test_trajectory_rejects_unsorted_or_duplicate_state_keys() -> None:
    baseline = _trajectory(TrajectoryKind.PREDICTED)

    with pytest.raises(ValueError, match="deterministic key order"):
        replace(baseline, slices=tuple(reversed(baseline.slices)))
    with pytest.raises(ValueError, match="unique object, metric, and time"):
        replace(baseline, slices=(baseline.slices[0], baseline.slices[0]))


def test_observed_trajectory_requires_independent_evidence() -> None:
    predicted = _trajectory(TrajectoryKind.PREDICTED)

    with pytest.raises(ValueError, match="independent observer evidence"):
        replace(predicted, kind=TrajectoryKind.OBSERVED)


def test_invariants_cover_every_matching_time_slice() -> None:
    trajectory = _trajectory(TrajectoryKind.PREDICTED)
    results = evaluate_dynamic_invariants(
        trajectory,
        (
            DynamicInvariant(
                "latency-limit",
                "latency_p99_ms",
                InvariantOperator.LESS_THAN_OR_EQUAL,
                75.0,
                target_ref="resource:api",
            ),
        ),
    )

    assert results[0].status is InvariantStatus.VIOLATED
    assert results[0].violating_keys == (trajectory.slices[1].key,)


def test_incomplete_trajectory_never_passes_invariant() -> None:
    trajectory = _trajectory(
        TrajectoryKind.PREDICTED,
        complete=False,
        truncated=True,
    )

    result = evaluate_dynamic_invariants(
        trajectory,
        (
            DynamicInvariant(
                "capacity-floor",
                "replicas",
                InvariantOperator.GREATER_THAN_OR_EQUAL,
                2.0,
            ),
        ),
    )[0]

    assert result.status is InvariantStatus.UNSCORABLE


def test_independent_observation_closes_matched_and_mismatched_trajectories() -> None:
    predicted = _trajectory(TrajectoryKind.PREDICTED)
    matched = close_trajectory_outcome(
        predicted,
        _trajectory(TrajectoryKind.OBSERVED, second_value=81.0),
        absolute_tolerance=1.0,
    )
    mismatched = close_trajectory_outcome(
        predicted,
        _trajectory(TrajectoryKind.OBSERVED, second_value=90.0),
        relative_tolerance=0.05,
    )

    assert matched.status is TrajectoryOutcomeStatus.MATCHED
    assert matched.challenger_eligible is True
    assert matched.compared_slices == 2
    assert mismatched.status is TrajectoryOutcomeStatus.MISMATCHED
    assert mismatched.mismatched_keys


def test_incomplete_or_censored_observation_cannot_update_challenger() -> None:
    predicted = _trajectory(TrajectoryKind.PREDICTED)
    incomplete = close_trajectory_outcome(
        predicted,
        _trajectory(
            TrajectoryKind.OBSERVED,
            complete=False,
            truncated=True,
        ),
    )
    censored = close_trajectory_outcome(
        predicted,
        _trajectory(
            TrajectoryKind.OBSERVED,
            censoring_refs=("intervention:other",),
        ),
    )

    assert incomplete.status is TrajectoryOutcomeStatus.INCOMPLETE
    assert incomplete.challenger_eligible is False
    assert censored.status is TrajectoryOutcomeStatus.INTERVENTION_CENSORED
    assert censored.challenger_eligible is False


def test_trajectory_identity_mismatch_is_unscorable() -> None:
    predicted = _trajectory(TrajectoryKind.PREDICTED)
    observed = replace(
        _trajectory(TrajectoryKind.OBSERVED),
        base_snapshot_id="snapshot-other",
    )

    outcome = close_trajectory_outcome(predicted, observed)

    assert outcome.status is TrajectoryOutcomeStatus.UNSCORABLE
    assert outcome.reason == "trajectory_identity_mismatch"


def test_graph_or_inventory_revision_mismatch_is_unscorable() -> None:
    predicted = _trajectory(TrajectoryKind.PREDICTED)
    observed = _trajectory(TrajectoryKind.OBSERVED)

    graph_mismatch = close_trajectory_outcome(
        predicted,
        replace(observed, graph_revision="graph-other"),
    )
    inventory_mismatch = close_trajectory_outcome(
        predicted,
        replace(observed, inventory_generation="inventory-other"),
    )

    assert graph_mismatch.status is TrajectoryOutcomeStatus.UNSCORABLE
    assert inventory_mismatch.status is TrajectoryOutcomeStatus.UNSCORABLE
