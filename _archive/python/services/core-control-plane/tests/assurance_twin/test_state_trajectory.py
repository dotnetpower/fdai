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
    StateStoreTrajectoryEpisodeLedger,
    TrajectoryEpisodeConflictError,
    TrajectoryKind,
    TrajectoryOutcomeStatus,
    close_trajectory_outcome,
    evaluate_dynamic_invariants,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

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


async def test_trajectory_ledger_validates_configuration_and_recording_inputs() -> None:
    store = InMemoryStateStore()
    with pytest.raises(ValueError, match="max_retries MUST be >= 1"):
        StateStoreTrajectoryEpisodeLedger(store, max_retries=0)
    with pytest.raises(ValueError, match="max_retries MUST be >= 1"):
        StateStoreTrajectoryEpisodeLedger(store, max_retries=True)

    ledger = StateStoreTrajectoryEpisodeLedger(store)
    predicted = _trajectory(TrajectoryKind.PREDICTED)
    observed = _trajectory(TrajectoryKind.OBSERVED)

    with pytest.raises(ValueError, match="MUST use predicted kind"):
        await ledger.record_prediction(
            observed,
            challenger_model_refs=("model@1.0.0",),
            recorded_by="Forseti",
            recorded_at=_NOW,
        )
    with pytest.raises(ValueError, match="MUST be sorted, unique, and bounded"):
        await ledger.record_prediction(
            predicted,
            challenger_model_refs=(),
            recorded_by="Forseti",
            recorded_at=_NOW,
        )
    with pytest.raises(ValueError, match="MUST be timezone-aware"):
        await ledger.record_prediction(
            predicted,
            challenger_model_refs=("model@1.0.0",),
            recorded_by="Forseti",
            recorded_at=datetime(2026, 8, 4, 0, 0),
        )
    with pytest.raises(ValueError, match="recorded_by MUST be non-empty"):
        await ledger.record_prediction(
            predicted,
            challenger_model_refs=("model@1.0.0",),
            recorded_by=" ",
            recorded_at=_NOW,
        )
    with pytest.raises(ValueError, match="open-episode limit"):
        await ledger.list_open(limit=0)
    with pytest.raises(ValueError, match="open-episode limit"):
        await ledger.list_open(limit=True)


async def test_trajectory_ledger_records_lists_and_closes_episodes_idempotently() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreTrajectoryEpisodeLedger(store)
    predicted = _trajectory(TrajectoryKind.PREDICTED)
    observed_mismatch = _trajectory(TrajectoryKind.OBSERVED, second_value=95.0)
    closed_at = _NOW + timedelta(minutes=3)

    assert (
        await ledger.record_prediction(
            predicted,
            challenger_model_refs=("model@1.0.0",),
            recorded_by="Forseti",
            recorded_at=_NOW,
        )
        is True
    )
    assert (
        await ledger.record_prediction(
            predicted,
            challenger_model_refs=("model@1.0.0",),
            recorded_by="Forseti",
            recorded_at=_NOW,
        )
        is False
    )
    with pytest.raises(TrajectoryEpisodeConflictError, match="prediction identity conflict"):
        await ledger.record_prediction(
            predicted,
            challenger_model_refs=("other@1.0.0",),
            recorded_by="Forseti",
            recorded_at=_NOW,
        )

    open_episodes = await ledger.list_open()
    assert len(open_episodes) == 1
    assert open_episodes[0].predicted == predicted

    with pytest.raises(ValueError, match="MUST follow the observation horizon"):
        await ledger.close(
            prediction_digest=predicted.digest,
            observed=observed_mismatch,
            recorded_at=_NOW + timedelta(minutes=1),
        )
    with pytest.raises(ValueError, match="prediction digest MUST be SHA-256"):
        await ledger.close(
            prediction_digest="bad-digest",
            observed=observed_mismatch,
            recorded_at=closed_at,
        )
    with pytest.raises(KeyError, match="episode was not found"):
        await ledger.close(
            prediction_digest="0" * 64,
            observed=observed_mismatch,
            recorded_at=closed_at,
        )

    first_close = await ledger.close(
        prediction_digest=predicted.digest,
        observed=observed_mismatch,
        recorded_at=closed_at,
    )
    assert first_close.closed is True
    assert first_close.duplicate is False
    assert first_close.outcome.status is TrajectoryOutcomeStatus.MISMATCHED
    assert await ledger.list_open() == ()

    duplicate_close = await ledger.close(
        prediction_digest=predicted.digest,
        observed=observed_mismatch,
        recorded_at=closed_at,
    )
    assert duplicate_close.closed is True
    assert duplicate_close.duplicate is True
    assert duplicate_close.outcome.mismatched_keys == first_close.outcome.mismatched_keys

    with pytest.raises(TrajectoryEpisodeConflictError, match="closure observation conflict"):
        await ledger.close(
            prediction_digest=predicted.digest,
            observed=_trajectory(TrajectoryKind.OBSERVED, second_value=80.0),
            recorded_at=closed_at,
        )


async def test_trajectory_ledger_rejects_ineligible_closure_and_detects_conflicts() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreTrajectoryEpisodeLedger(store)
    predicted = _trajectory(TrajectoryKind.PREDICTED)
    closed_at = _NOW + timedelta(minutes=3)
    await ledger.record_prediction(
        predicted,
        challenger_model_refs=("model@1.0.0",),
        recorded_by="Forseti",
        recorded_at=_NOW,
    )

    rejected = await ledger.close(
        prediction_digest=predicted.digest,
        observed=_trajectory(TrajectoryKind.OBSERVED, complete=False, truncated=True),
        recorded_at=closed_at,
    )
    assert rejected.closed is False
    assert rejected.duplicate is False
    assert rejected.outcome.status is TrajectoryOutcomeStatus.INCOMPLETE

    key = f"dynamic-trajectory-episode:{predicted.digest}"
    raw_episode = dict(await store.read_state(key) or {})
    tampered_predicted = {**dict(raw_episode["predicted"]), "base_snapshot_id": "tampered"}
    await store.write_state(key, {**raw_episode, "predicted": tampered_predicted})
    with pytest.raises(TrajectoryEpisodeConflictError, match="prediction identity mismatch"):
        await ledger.close(
            prediction_digest=predicted.digest,
            observed=_trajectory(TrajectoryKind.OBSERVED),
            recorded_at=closed_at,
        )

    class _AlwaysConflictStore(InMemoryStateStore):
        async def compare_and_set_state_with_audit(
            self,
            state_key: str,
            value: dict[str, object],
            *,
            expected_revision: int,
            audit_entry: dict[str, object],
        ) -> bool:
            _ = (state_key, value, expected_revision, audit_entry)
            return False

    conflict_store = _AlwaysConflictStore()
    conflict_ledger = StateStoreTrajectoryEpisodeLedger(conflict_store, max_retries=2)
    await conflict_ledger.record_prediction(
        predicted,
        challenger_model_refs=("model@1.0.0",),
        recorded_by="Forseti",
        recorded_at=_NOW,
    )
    with pytest.raises(TrajectoryEpisodeConflictError, match="closure revision conflict"):
        await conflict_ledger.close(
            prediction_digest=predicted.digest,
            observed=_trajectory(TrajectoryKind.OBSERVED),
            recorded_at=closed_at,
        )


async def test_trajectory_ledger_rejects_corrupted_stored_payloads() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreTrajectoryEpisodeLedger(store)
    predicted = _trajectory(TrajectoryKind.PREDICTED)
    await ledger.record_prediction(
        predicted,
        challenger_model_refs=("model@1.0.0",),
        recorded_by="Forseti",
        recorded_at=_NOW,
    )
    key = f"dynamic-trajectory-episode:{predicted.digest}"
    valid_raw = dict(await store.read_state(key) or {})
    valid_predicted = dict(valid_raw["predicted"])
    valid_slice = dict(valid_predicted["slices"][0])

    await store.write_state(key, {**valid_raw, "predicted": "not-an-object"})
    with pytest.raises(ValueError, match="MUST be an object"):
        await ledger.list_open()

    await store.write_state(
        key,
        {**valid_raw, "predicted": {**valid_predicted, "slices": "not-a-list"}},
    )
    with pytest.raises(ValueError, match="slices MUST be a list"):
        await ledger.list_open()

    await store.write_state(
        key,
        {
            **valid_raw,
            "predicted": {**valid_predicted, "slices": [{**valid_slice, "object_ref": ""}]},
        },
    )
    with pytest.raises(ValueError, match="object_ref MUST be non-empty"):
        await ledger.list_open()

    await store.write_state(
        key,
        {
            **valid_raw,
            "predicted": {**valid_predicted, "slices": [{**valid_slice, "model_ref": ""}]},
        },
    )
    with pytest.raises(ValueError, match="model_ref MUST be non-empty when present"):
        await ledger.list_open()

    await store.write_state(
        key,
        {**valid_raw, "challenger_model_refs": [123]},
    )
    with pytest.raises(ValueError, match="challenger_model_refs MUST be a string list"):
        await ledger.list_open()

    observed = _trajectory(TrajectoryKind.OBSERVED)
    await store.write_state(key, valid_raw)
    await ledger.close(
        prediction_digest=predicted.digest,
        observed=observed,
        recorded_at=_NOW + timedelta(minutes=3),
    )
    closed_raw = dict(await store.read_state(key) or {})
    closed_outcome = dict(closed_raw["outcome"])

    await store.write_state(
        key,
        {**closed_raw, "outcome": {**closed_outcome, "mismatched_keys": "bad"}},
    )
    with pytest.raises(ValueError, match="mismatched_keys MUST be a list"):
        await ledger.close(
            prediction_digest=predicted.digest,
            observed=observed,
            recorded_at=_NOW + timedelta(minutes=3),
        )

    await store.write_state(
        key,
        {**closed_raw, "outcome": {**closed_outcome, "mismatched_keys": [["only-two", "items"]]}},
    )
    with pytest.raises(ValueError, match="mismatch key MUST contain three values"):
        await ledger.close(
            prediction_digest=predicted.digest,
            observed=observed,
            recorded_at=_NOW + timedelta(minutes=3),
        )
