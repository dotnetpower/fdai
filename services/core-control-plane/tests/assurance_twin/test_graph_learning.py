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


def test_graph_learning_observation_validates_bounds_and_timestamps() -> None:
    model = _model(EffectModelStatus.CHALLENGER)
    base = _observation(model)

    with pytest.raises(ValueError, match="model_ref MUST be bounded"):
        replace(base, model_ref="")
    with pytest.raises(ValueError, match="slice identity MUST be non-empty"):
        replace(base, object_ref=" ")
    with pytest.raises(ValueError, match="trajectory digests MUST be SHA-256"):
        replace(base, prediction_digest="bad")
    with pytest.raises(ValueError, match="values MUST be finite"):
        replace(base, observed_value=float("nan"))
    with pytest.raises(ValueError, match="timestamps MUST be timezone-aware"):
        replace(base, observed_at=datetime(2026, 8, 4, 0, 1))
    with pytest.raises(ValueError, match="observation MUST NOT follow recording"):
        replace(
            base,
            observed_at=_NOW + timedelta(minutes=3),
            recorded_at=_NOW + timedelta(minutes=2),
        )
    with pytest.raises(ValueError, match="evidence_refs MUST be non-empty"):
        replace(base, evidence_refs=())


def test_update_graph_challenger_rejects_mismatch_duplicate_cutoff_and_overflow() -> None:
    model = _model(EffectModelStatus.CHALLENGER)
    obs = _observation(model)

    mismatch = update_graph_challenger(model, replace(obs, model_ref="other@1.0.0:r1"))
    assert mismatch.accepted is False
    assert mismatch.reason == "observation_model_mismatch"

    first = update_graph_challenger(model, obs)
    duplicate = update_graph_challenger(first.model, obs)
    assert duplicate.accepted is False
    assert duplicate.reason == "observation_already_applied"

    stale_cutoff = update_graph_challenger(
        model,
        replace(obs, observed_at=_NOW - timedelta(minutes=1), recorded_at=_NOW),
    )
    assert stale_cutoff.accepted is False
    assert stale_cutoff.reason == "observation_not_after_learning_cutoff"

    overflow = update_graph_challenger(
        model,
        replace(obs, predicted_value=-1e308, observed_value=1e308),
    )
    assert overflow.accepted is False
    assert overflow.reason == "observation_arithmetic_non_finite"


async def test_graph_registry_validates_limits_registration_and_cas_outcomes() -> None:
    with pytest.raises(ValueError, match="limits MUST be positive"):
        StateStoreGraphEffectModelRegistry(InMemoryStateStore(), max_models=0)

    store = InMemoryStateStore()
    registry = StateStoreGraphEffectModelRegistry(store, max_retries=2)
    challenger = _model(EffectModelStatus.CHALLENGER)
    with pytest.raises(ValueError, match="registered_by MUST be non-empty"):
        await registry.register(challenger, registered_by="")
    assert await registry.register(challenger, registered_by="Mimir") is True

    rejected = await registry.update_from_observation(
        replace(_observation(challenger), complete=False)
    )
    assert rejected.accepted is False
    assert rejected.reason == "observation_incomplete"
    assert rejected.model_ref == challenger.ref

    class _ConflictStore(InMemoryStateStore):
        def __init__(self, *, disappear: bool) -> None:
            super().__init__()
            self._disappear = disappear

        async def compare_and_set_state_with_audit(
            self,
            key: str,
            value: dict[str, object],
            *,
            expected_revision: int,
            audit_entry: dict[str, object],
        ) -> bool:
            _ = (value, expected_revision, audit_entry)
            if self._disappear:
                self._state.pop(key, None)
            return False

    disappearing_store = _ConflictStore(disappear=True)
    disappearing_registry = StateStoreGraphEffectModelRegistry(disappearing_store, max_retries=2)
    assert await disappearing_registry.register(challenger, registered_by="Mimir") is True
    disappeared = await disappearing_registry.update_from_observation(_observation(challenger))
    assert disappeared.accepted is False
    assert disappeared.reason == "challenger_disappeared"

    conflict_store = _ConflictStore(disappear=False)
    conflict_registry = StateStoreGraphEffectModelRegistry(conflict_store, max_retries=2)
    assert await conflict_registry.register(challenger, registered_by="Mimir") is True
    conflict = await conflict_registry.update_from_observation(_observation(challenger))
    assert conflict.accepted is False
    assert conflict.reason == "revision_conflict"


async def test_graph_registry_rejects_corrupted_stored_records() -> None:
    store = InMemoryStateStore()
    registry = StateStoreGraphEffectModelRegistry(store)
    model = _model(EffectModelStatus.ACTIVE)
    assert await registry.register(model, registered_by="Mimir") is True
    key = next(iter(store._state))
    valid_raw = dict(store._state[key])

    await store.write_state(key, {**valid_raw, "link_path": "not-a-list"})
    with pytest.raises(ValueError, match="link_path MUST be a string list"):
        await registry.list_models(
            status=EffectModelStatus.ACTIVE,
            trigger_refs=(model.trigger_ref,),
        )

    await store.write_state(key, {**valid_raw, "applied_observation_digests": [123]})
    with pytest.raises(ValueError, match="observation digests MUST be a string list"):
        await registry.list_models(
            status=EffectModelStatus.ACTIVE,
            trigger_refs=(model.trigger_ref,),
        )

    await store.write_state(key, {**valid_raw, "model_id": ""})
    with pytest.raises(ValueError, match="model_id MUST be non-empty"):
        await registry.list_models(
            status=EffectModelStatus.ACTIVE,
            trigger_refs=(model.trigger_ref,),
        )

    await store.write_state(key, {**valid_raw, "learned_through": "2026-08-04T00:00:00"})
    with pytest.raises(ValueError, match="learned_through MUST be timezone-aware"):
        await registry.list_models(
            status=EffectModelStatus.ACTIVE,
            trigger_refs=(model.trigger_ref,),
        )
