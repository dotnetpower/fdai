from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.assurance_twin import (
    CausalEvidenceGrade,
    EffectModelStatus,
    GraphDynamicClosureCoordinator,
    GraphDynamicClosureRunner,
    GraphEffectModel,
    MetricGraphTrajectoryOutcomeSource,
    OperationalStateTrajectory,
    StateSlice,
    StateStoreGraphEffectModelRegistry,
    StateStoreTrajectoryEpisodeLedger,
    TrajectoryClosureCommand,
    TrajectoryEpisodeConflictError,
    TrajectoryKind,
    TrajectoryOutcomeStatus,
)
from fdai.shared.providers.metric import MetricPoint, StaticMetricProvider
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 8, 4, tzinfo=UTC)


async def _commands(source: MetricGraphTrajectoryOutcomeSource):
    return tuple([item async for item in source.outcomes()])


def _model(status: EffectModelStatus) -> GraphEffectModel:
    return GraphEffectModel(
        model_id="graph-effect.scale-latency",
        version="1.0.0",
        revision=1,
        status=status,
        trigger_ref="ops.scale-out",
        source_type="Workload",
        link_path=("implements",),
        target_type="BusinessService",
        target_metric="latency",
        propagation_lag_seconds=30,
        gain=5.0,
        offset=0.0,
        interval_radius=1.0,
        evidence_grade=CausalEvidenceGrade.QUASI_EXPERIMENTAL,
        causal_evidence_receipt_digest="a" * 64,
        learned_through=_NOW,
    )


def _trajectory(
    kind: TrajectoryKind,
    *,
    value: float = 60.0,
    complete: bool = True,
    truncated: bool = False,
    censoring_refs: tuple[str, ...] = (),
    base_snapshot_id: str = "snapshot-1",
) -> OperationalStateTrajectory:
    observed = kind is TrajectoryKind.OBSERVED
    challenger = _model(EffectModelStatus.CHALLENGER)
    return OperationalStateTrajectory(
        kind=kind,
        ontology_release="sha256:" + "b" * 64,
        graph_revision="graph-1",
        inventory_generation="inventory-1",
        base_snapshot_id=base_snapshot_id,
        evidence_cutoff=_NOW,
        horizon_end=_NOW + timedelta(minutes=2),
        slices=(
            StateSlice(
                object_ref="service:checkout",
                object_type="BusinessService",
                metric="latency",
                value=value,
                effective_at=_NOW + timedelta(minutes=1),
                evidence_refs=("metric:latency",) if observed else (),
                model_ref=None if observed else challenger.ref,
                independent_observer=observed,
            ),
        ),
        intervention_refs=("intervention:scale",),
        censoring_refs=censoring_refs,
        source_watermarks=("metrics:1",),
        complete=complete,
        truncated=truncated,
        truncation_reasons=("telemetry_gap",) if truncated else (),
    )


async def _coordinator() -> tuple[
    InMemoryStateStore,
    StateStoreGraphEffectModelRegistry,
    GraphDynamicClosureCoordinator,
    GraphEffectModel,
    GraphEffectModel,
]:
    store = InMemoryStateStore()
    registry = StateStoreGraphEffectModelRegistry(store)
    active = _model(EffectModelStatus.ACTIVE)
    challenger = _model(EffectModelStatus.CHALLENGER)
    assert await registry.register(active, registered_by="Mimir") is True
    assert await registry.register(challenger, registered_by="Mimir") is True
    ledger = StateStoreTrajectoryEpisodeLedger(store)
    assert (
        await ledger.record_prediction(
            _trajectory(TrajectoryKind.PREDICTED),
            challenger_model_refs=(challenger.ref,),
            recorded_by="Norns",
            recorded_at=_NOW + timedelta(seconds=1),
        )
        is True
    )
    return (
        store,
        registry,
        GraphDynamicClosureCoordinator(
            ledger=ledger,
            registry=registry,
            audit_store=store,
        ),
        active,
        challenger,
    )


async def test_metric_source_builds_complete_independent_observation() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreTrajectoryEpisodeLedger(store)
    predicted = _trajectory(TrajectoryKind.PREDICTED)
    challenger = _model(EffectModelStatus.CHALLENGER)
    await ledger.record_prediction(
        predicted,
        challenger_model_refs=(challenger.ref,),
        recorded_by="Forseti",
        recorded_at=_NOW,
    )
    source = MetricGraphTrajectoryOutcomeSource(
        ledger=ledger,
        metrics=StaticMetricProvider(
            (
                MetricPoint(
                    metric_name="latency",
                    at=_NOW + timedelta(minutes=1, seconds=10),
                    value=61.0,
                    labels={"resource_id": "service:checkout"},
                ),
            )
        ),
        clock=lambda: _NOW + timedelta(minutes=8),
    )

    commands = await _commands(source)

    assert len(commands) == 1
    observed = commands[0].observed
    assert observed.kind is TrajectoryKind.OBSERVED
    assert observed.slices[0].value == 61.0
    assert observed.slices[0].independent_observer is True
    assert observed.slices[0].evidence_refs[0].startswith("metric:")


async def test_metric_source_keeps_episode_open_when_telemetry_is_missing() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreTrajectoryEpisodeLedger(store)
    predicted = _trajectory(TrajectoryKind.PREDICTED)
    challenger = _model(EffectModelStatus.CHALLENGER)
    await ledger.record_prediction(
        predicted,
        challenger_model_refs=(challenger.ref,),
        recorded_by="Forseti",
        recorded_at=_NOW,
    )
    source = MetricGraphTrajectoryOutcomeSource(
        ledger=ledger,
        metrics=StaticMetricProvider(()),
        clock=lambda: _NOW + timedelta(minutes=8),
    )

    assert await _commands(source) == ()
    assert len(await ledger.list_open()) == 1


async def test_metric_source_bounds_a_stalled_provider_query() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreTrajectoryEpisodeLedger(store)
    predicted = _trajectory(TrajectoryKind.PREDICTED)
    challenger = _model(EffectModelStatus.CHALLENGER)
    await ledger.record_prediction(
        predicted,
        challenger_model_refs=(challenger.ref,),
        recorded_by="Forseti",
        recorded_at=_NOW,
    )
    query_started = asyncio.Event()
    query_cancelled = asyncio.Event()
    never_complete = asyncio.Event()

    class StalledMetricProvider:
        async def query(self, query):  # type: ignore[no-untyped-def]
            query_started.set()
            try:
                await never_complete.wait()
                if False:
                    yield MetricPoint(
                        metric_name=query.metric_name,
                        at=query.since,
                        value=0.0,
                        labels=query.labels,
                    )
            finally:
                query_cancelled.set()

    source = MetricGraphTrajectoryOutcomeSource(
        ledger=ledger,
        metrics=StalledMetricProvider(),
        clock=lambda: _NOW + timedelta(minutes=8),
        query_timeout_seconds=0.01,
    )

    async with asyncio.timeout(0.5):
        commands = await _commands(source)
        await query_started.wait()
        await query_cancelled.wait()

    assert commands == ()
    assert len(await ledger.list_open()) == 1


@pytest.mark.parametrize(
    ("observed_value", "expected_status"),
    [(60.0, "matched"), (67.0, "mismatched")],
)
async def test_complete_matched_and_mismatched_outcomes_update_only_challenger(
    observed_value: float,
    expected_status: str,
) -> None:
    _, registry, coordinator, active, challenger = await _coordinator()
    predicted = _trajectory(TrajectoryKind.PREDICTED)

    result = await coordinator.close_and_update(
        prediction_digest=predicted.digest,
        observed=_trajectory(TrajectoryKind.OBSERVED, value=observed_value),
        recorded_at=_NOW + timedelta(minutes=2),
    )
    active_models = await registry.list_models(
        status=EffectModelStatus.ACTIVE,
        trigger_refs=("ops.scale-out",),
    )
    challenger_models = await registry.list_models(
        status=EffectModelStatus.CHALLENGER,
        trigger_refs=("ops.scale-out",),
    )

    assert result.outcome_status.value == expected_status
    assert result.closed is True
    assert result.update_count == 1
    assert active_models == (active,)
    assert challenger_models[0].revision == challenger.revision + 1
    assert challenger_models[0].sample_count == 1


@pytest.mark.parametrize(
    "observed",
    [
        _trajectory(
            TrajectoryKind.OBSERVED,
            complete=False,
            truncated=True,
        ),
        _trajectory(
            TrajectoryKind.OBSERVED,
            censoring_refs=("intervention:other",),
        ),
    ],
)
async def test_censored_or_incomplete_outcome_never_updates_challenger(
    observed: OperationalStateTrajectory,
) -> None:
    _, registry, coordinator, _, challenger = await _coordinator()
    predicted = _trajectory(TrajectoryKind.PREDICTED)

    result = await coordinator.close_and_update(
        prediction_digest=predicted.digest,
        observed=observed,
        recorded_at=_NOW + timedelta(minutes=2),
    )
    loaded = await registry.list_models(
        status=EffectModelStatus.CHALLENGER,
        trigger_refs=("ops.scale-out",),
    )

    assert result.closed is False
    assert result.update_count == 0
    assert loaded == (challenger,)


async def test_identity_mismatch_fails_closed_without_learning() -> None:
    _, registry, coordinator, _, challenger = await _coordinator()
    predicted = _trajectory(TrajectoryKind.PREDICTED)

    result = await coordinator.close_and_update(
        prediction_digest=predicted.digest,
        observed=_trajectory(
            TrajectoryKind.OBSERVED,
            base_snapshot_id="snapshot-other",
        ),
        recorded_at=_NOW + timedelta(minutes=2),
    )
    loaded = await registry.list_models(
        status=EffectModelStatus.CHALLENGER,
        trigger_refs=("ops.scale-out",),
    )

    assert result.outcome_status is TrajectoryOutcomeStatus.UNSCORABLE
    assert result.reason == "trajectory_identity_mismatch"
    assert result.closed is False
    assert loaded == (challenger,)


async def test_closure_before_observation_horizon_is_rejected() -> None:
    _, _, coordinator, _, _ = await _coordinator()
    predicted = _trajectory(TrajectoryKind.PREDICTED)

    with pytest.raises(ValueError, match="follow the observation horizon"):
        await coordinator.close_and_update(
            prediction_digest=predicted.digest,
            observed=_trajectory(TrajectoryKind.OBSERVED),
            recorded_at=_NOW + timedelta(minutes=1),
        )


async def test_duplicate_closure_replay_is_idempotent() -> None:
    store, registry, coordinator, _, _ = await _coordinator()
    predicted = _trajectory(TrajectoryKind.PREDICTED)
    observed = _trajectory(TrajectoryKind.OBSERVED, value=67.0)

    first = await coordinator.close_and_update(
        prediction_digest=predicted.digest,
        observed=observed,
        recorded_at=_NOW + timedelta(minutes=2),
    )
    second = await coordinator.close_and_update(
        prediction_digest=predicted.digest,
        observed=observed,
        recorded_at=_NOW + timedelta(minutes=3),
    )
    loaded = await registry.list_models(
        status=EffectModelStatus.CHALLENGER,
        trigger_refs=("ops.scale-out",),
    )

    assert first.update_count == 1
    assert second.duplicate is True
    assert second.update_count == 0
    assert loaded[0].revision == 2
    assert loaded[0].sample_count == 1
    closure_audits = [
        item
        for item in store.audit_entries
        if item["entry"].get("action_kind") == "dynamic.trajectory_outcome.closed"
    ]
    assert len(closure_audits) == 1


async def test_duplicate_prediction_with_different_identity_fails_closed() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreTrajectoryEpisodeLedger(store)
    predicted = _trajectory(TrajectoryKind.PREDICTED)
    challenger_ref = _model(EffectModelStatus.CHALLENGER).ref
    assert (
        await ledger.record_prediction(
            predicted,
            challenger_model_refs=(challenger_ref,),
            recorded_by="Norns",
            recorded_at=_NOW,
        )
        is True
    )

    with pytest.raises(TrajectoryEpisodeConflictError, match="prediction identity conflict"):
        await ledger.record_prediction(
            predicted,
            challenger_model_refs=("graph-effect.other@1.0.0:r1",),
            recorded_by="Norns",
            recorded_at=_NOW,
        )


class _OutcomeSource:
    def __init__(self, *commands: TrajectoryClosureCommand) -> None:
        self._commands = commands

    async def outcomes(self) -> AsyncIterator[TrajectoryClosureCommand]:
        for command in self._commands:
            yield command


class _FailFirstCoordinator:
    def __init__(self, delegate: GraphDynamicClosureCoordinator) -> None:
        self._delegate = delegate
        self._calls = 0

    async def close_and_update(self, **kwargs):  # type: ignore[no-untyped-def]
        self._calls += 1
        if self._calls == 1:
            raise TrajectoryEpisodeConflictError("poison episode")
        return await self._delegate.close_and_update(**kwargs)


async def test_off_path_runner_audits_without_active_mutation_or_promotion() -> None:
    store, registry, coordinator, active, _ = await _coordinator()
    predicted = _trajectory(TrajectoryKind.PREDICTED)
    runner = GraphDynamicClosureRunner(
        outcome_source=_OutcomeSource(
            TrajectoryClosureCommand(
                prediction_digest=predicted.digest,
                observed=_trajectory(TrajectoryKind.OBSERVED, value=63.0),
                recorded_at=_NOW + timedelta(minutes=2),
            )
        ),
        coordinator=coordinator,
        audit_store=store,
        clock=lambda: _NOW + timedelta(minutes=3),
    )

    reports = await runner.run_once()
    active_models = await registry.list_models(
        status=EffectModelStatus.ACTIVE,
        trigger_refs=("ops.scale-out",),
    )
    run_audit = store.audit_entries[-1]["entry"]

    assert reports[0].update_count == 1
    assert active_models == (active,)
    assert run_audit["action_kind"] == "dynamic.graph_closure.run"
    assert run_audit["active_model_mutated"] is False
    assert run_audit["promotion_applied"] is False


async def test_off_path_runner_isolates_poison_episode() -> None:
    store, _, coordinator, _, _ = await _coordinator()
    predicted = _trajectory(TrajectoryKind.PREDICTED)
    command = TrajectoryClosureCommand(
        prediction_digest=predicted.digest,
        observed=_trajectory(TrajectoryKind.OBSERVED, value=63.0),
        recorded_at=_NOW + timedelta(minutes=2),
    )
    runner = GraphDynamicClosureRunner(
        outcome_source=_OutcomeSource(command, command),
        coordinator=_FailFirstCoordinator(coordinator),  # type: ignore[arg-type]
        audit_store=store,
        clock=lambda: _NOW + timedelta(minutes=3),
    )

    reports = await runner.run_once()

    assert len(reports) == 1
    assert reports[0].closed is True
    failure = next(
        item["entry"]
        for item in store.audit_entries
        if item["entry"].get("action_kind") == "dynamic.graph_closure.failed"
    )
    assert failure["reason"] == "TrajectoryEpisodeConflictError"
    assert store.audit_entries[-1]["entry"]["failure_count"] == 1
