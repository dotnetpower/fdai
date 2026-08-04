from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.assurance_twin import (
    CausalEvidenceGrade,
    EffectModelStatus,
    GraphEffectModel,
    GraphModelLearningObservation,
    StateStoreGraphEffectModelRegistry,
    update_graph_challenger,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 8, 4, tzinfo=UTC)


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


def _observation(model: GraphEffectModel) -> GraphModelLearningObservation:
    return GraphModelLearningObservation(
        model_ref=model.ref,
        prediction_digest="b" * 64,
        observation_digest="c" * 64,
        object_ref="service:checkout",
        metric="latency",
        predicted_value=60.0,
        observed_value=66.0,
        observed_at=_NOW + timedelta(minutes=1),
        recorded_at=_NOW + timedelta(minutes=2),
        evidence_refs=("metric:latency",),
        independent_observer=True,
        complete=True,
    )


def test_only_graph_challenger_learns_from_complete_independent_observation() -> None:
    active = _model(EffectModelStatus.ACTIVE)
    challenger = _model(EffectModelStatus.CHALLENGER)

    active_update = update_graph_challenger(active, _observation(active))
    challenger_update = update_graph_challenger(challenger, _observation(challenger))

    assert active_update.accepted is False
    assert active_update.reason == "active_model_is_immutable"
    assert challenger_update.accepted is True
    assert challenger_update.model.revision == 2
    assert challenger_update.model.sample_count == 1
    assert challenger_update.model.offset == 6.0
    assert challenger_update.model.mean_absolute_error == 6.0


def test_incomplete_nonindependent_or_censored_observation_is_rejected() -> None:
    model = _model(EffectModelStatus.CHALLENGER)

    incomplete = update_graph_challenger(model, replace(_observation(model), complete=False))
    dependent = update_graph_challenger(
        model,
        replace(_observation(model), independent_observer=False),
    )
    censored = update_graph_challenger(
        model,
        replace(_observation(model), intervention_censored=True),
    )

    assert incomplete.reason == "observation_incomplete"
    assert dependent.reason == "observer_not_independent"
    assert censored.reason == "observation_intervention_censored"


def test_graph_challenger_never_drops_observation_deduplication_evidence() -> None:
    model = replace(
        _model(EffectModelStatus.CHALLENGER),
        applied_observation_digests=tuple(f"{index:064x}" for index in range(64)),
    )

    update = update_graph_challenger(model, _observation(model))

    assert update.accepted is False
    assert update.reason == "observation_digest_capacity_reached"
    assert update.model.applied_observation_digests == model.applied_observation_digests


async def test_graph_registry_keeps_active_immutable_and_updates_challenger() -> None:
    store = InMemoryStateStore()
    registry = StateStoreGraphEffectModelRegistry(store)
    active = _model(EffectModelStatus.ACTIVE)
    challenger = _model(EffectModelStatus.CHALLENGER)
    assert await registry.register(active, registered_by="Mimir") is True
    assert await registry.register(challenger, registered_by="Mimir") is True

    update = await registry.update_from_observation(_observation(challenger))
    active_models = await registry.list_models(
        status=EffectModelStatus.ACTIVE,
        trigger_refs=("ops.scale-out",),
    )
    challenger_models = await registry.list_models(
        status=EffectModelStatus.CHALLENGER,
        trigger_refs=("ops.scale-out",),
    )

    assert update.accepted is True
    assert active_models == (active,)
    assert challenger_models[0].revision == 2
    assert challenger_models[0].offset == 6.0
    action_kinds = [row["entry"]["action_kind"] for row in store.audit_entries]
    assert action_kinds == [
        "dynamic.graph_effect_model.registered",
        "dynamic.graph_effect_model.registered",
        "dynamic.graph_effect_model.challenger.updated",
    ]


async def test_graph_registry_applies_one_observation_at_most_once() -> None:
    store = InMemoryStateStore()
    registry = StateStoreGraphEffectModelRegistry(store)
    challenger = _model(EffectModelStatus.CHALLENGER)
    assert await registry.register(challenger, registered_by="Mimir") is True
    observation = _observation(challenger)

    first = await registry.update_from_observation(observation)
    second = await registry.update_from_observation(observation)
    loaded = await registry.list_models(
        status=EffectModelStatus.CHALLENGER,
        trigger_refs=("ops.scale-out",),
    )

    assert first.accepted is True
    assert second.accepted is False
    assert second.reason == "observation_already_applied"
    assert loaded[0].revision == 2
    assert loaded[0].sample_count == 1


async def test_graph_registry_rejects_unknown_challenger() -> None:
    registry = StateStoreGraphEffectModelRegistry(InMemoryStateStore())
    model = _model(EffectModelStatus.CHALLENGER)

    update = await registry.update_from_observation(_observation(model))

    assert update.accepted is False
    assert update.reason == "challenger_not_found_or_ambiguous"


async def test_graph_registry_fails_closed_on_truncated_status_partition() -> None:
    store = InMemoryStateStore()
    registry = StateStoreGraphEffectModelRegistry(store, max_models=1)
    model = _model(EffectModelStatus.ACTIVE)
    assert await registry.register(model, registered_by="Mimir") is True

    with pytest.raises(ValueError, match="partition is truncated"):
        await registry.list_models(
            status=EffectModelStatus.ACTIVE,
            trigger_refs=(model.trigger_ref,),
        )


async def test_graph_registry_rejects_update_when_challenger_partition_is_truncated() -> None:
    store = InMemoryStateStore()
    registry = StateStoreGraphEffectModelRegistry(store, max_models=1)
    model = _model(EffectModelStatus.CHALLENGER)
    assert await registry.register(model, registered_by="Mimir") is True

    result = await registry.update_from_observation(_observation(model))

    assert result.accepted is False
    assert result.reason == "challenger_registry_truncated"
