"""Exercise unavailable, corrupt, and stale feedback without inventing outcomes."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from functools import partial

import pytest
from fdai.core.assurance_twin import EffectModelStatus, StateStoreEffectModelRegistry
from fdai.core.assurance_twin.feedback_rebuild import rebuild_feedback
from fdai.core.assurance_twin.model_registry import _state_key
from fdai.shared.contracts.models import ResponseOutcome
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.assurance_twin.test_feedback_rebuild import _AS_OF, _admission, _corrected
from tests.assurance_twin.test_feedback_reliability import _challenger, _feedback
from tests.assurance_twin.test_model_registry import _NOW, _CurrentFixtureSource, _model, _registry

_KEY = _state_key(EffectModelStatus.CHALLENGER, "ops.scale-out", "latency_p99_ms")


async def test_registration_inspection_preserves_exact_and_legacy_seed_identity() -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    inspect = partial(
        registry.inspect_registration,
        status=EffectModelStatus.CHALLENGER,
        action_type_id="ops.scale-out",
        metric="latency_p99_ms",
    )
    assert await inspect() is None
    seed = _model(EffectModelStatus.CHALLENGER)
    await registry.register(seed, registered_by="Mimir")
    assert await inspect() == (seed, seed)
    stored = await store.read_state(_KEY)
    assert stored is not None
    legacy = dict(stored)
    for field in ("state_digest", "registered_seed", "registered_seed_digest"):
        legacy.pop(field)
    await store.write_state(_KEY, legacy)
    assert await inspect() == (seed, None)


@pytest.mark.parametrize("corruption", ["seed_shape", "seed_digest"])
async def test_registration_inspection_rejects_invalid_seed_metadata(corruption: str) -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")
    stored = await store.read_state(_KEY)
    assert stored is not None
    raw = dict(stored)
    raw.pop("state_digest")
    if corruption == "seed_shape":
        raw["registered_seed"] = False
    else:
        raw["registered_seed_digest"] = "f" * 64
    await store.write_state(_KEY, raw)
    with pytest.raises(ValueError, match="seed registration"):
        await registry.inspect_registration(
            status=EffectModelStatus.CHALLENGER,
            action_type_id="ops.scale-out",
            metric="latency_p99_ms",
        )


def test_registry_rejects_an_unbounded_retry_configuration() -> None:
    with pytest.raises(ValueError, match="max_retries"):
        StateStoreEffectModelRegistry(InMemoryStateStore(), max_retries=0)


async def test_registration_requires_an_attributed_actor() -> None:
    with pytest.raises(ValueError, match="registered_by"):
        await _registry(InMemoryStateStore()).register(
            _model(EffectModelStatus.CHALLENGER), registered_by=""
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("model_id", "", "model_id MUST be non-empty"),
        ("unit", "", "unit MUST be non-empty"),
        ("prediction_model_ref", 1, "prediction_model_ref MUST be non-empty"),
        ("learned_at", _NOW.replace(tzinfo=None).isoformat(), "timezone-aware"),
    ],
)
async def test_invalid_legacy_projection_is_an_explicit_error(
    field: str,
    value: object,
    message: str,
) -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")
    stored = await store.read_state(_KEY)
    assert stored is not None
    raw = dict(stored)
    raw.pop("state_digest")
    raw[field] = value
    await store.write_state(_KEY, raw)
    with pytest.raises(ValueError, match=message):
        await _challenger(registry)


async def test_tampered_sealed_projection_cannot_be_used_after_restart() -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")
    stored = await store.read_state(_KEY)
    assert stored is not None
    raw = dict(stored)
    raw["bias_correction"] = 100.0
    await store.write_state(_KEY, raw)
    with pytest.raises(ValueError, match="state digest is invalid"):
        await _challenger(_registry(store))


async def test_generation_replay_correction_and_dependency_are_not_new_samples() -> None:
    store = InMemoryStateStore()
    seed = _model(EffectModelStatus.CHALLENGER)
    original = _registry(store)
    await original.register(seed, registered_by="Mimir")
    first = _feedback(1)
    candidate = rebuild_feedback(seed=seed, outcomes=(first,), as_of=_AS_OF, complete=True)
    registry = StateStoreEffectModelRegistry(
        store,
        clock=lambda: _AS_OF,
        feedback_source=_CurrentFixtureSource(),
    )
    assert (
        await registry.rebuild_challenger(
            seed=seed,
            outcomes=(first,),
            as_of=_AS_OF,
            expected_revision=1,
            admission=_admission(candidate.input_manifest_digest),
        )
    ).accepted
    assert (await registry.update_from_outcome(first)).reason == "outcome_already_applied"
    assert (
        await registry.update_from_outcome(_corrected(first))
    ).reason == "outcome_revision_requires_rebuild"
    second = _feedback(2)
    assert first.prediction_snapshot is not None and second.prediction_snapshot is not None
    dependent = ResponseOutcome.model_validate(
        {
            **second.model_dump(),
            "prediction_snapshot": {
                **second.prediction_snapshot.model_dump(),
                "independence_key": first.prediction_snapshot.independence_key,
            },
        }
    )
    assert (
        await registry.update_from_outcome(dependent)
    ).reason == "dependent_event_already_learned"
    unavailable = StateStoreEffectModelRegistry(store, clock=lambda: _AS_OF)
    assert await _challenger(unavailable) is None
    assert (
        await unavailable.update_from_outcome(_feedback(3))
    ).reason == "model_generation_sources_unavailable"
    loaded = await _challenger(registry)
    assert loaded is not None and loaded.sample_count == 1


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("unregistered", "challenger_not_registered"),
        ("wrong_revision", "revision_conflict"),
        ("stale_source", "rebuild_source_changed"),
        ("wrong_purpose", "rebuild_evidence_invalid"),
        ("missing_prediction", "rebuild_prediction_unavailable"),
        ("admission_expires", "rebuild_evidence_expired"),
    ],
)
async def test_rebuild_refuses_unavailable_or_stale_evidence(case: str, reason: str) -> None:
    store = InMemoryStateStore()
    seed = _model(EffectModelStatus.CHALLENGER)
    first = _feedback(1)
    candidate = rebuild_feedback(seed=seed, outcomes=(first,), as_of=_AS_OF, complete=True)
    if case != "unregistered":
        registrar = (
            StateStoreEffectModelRegistry(store)
            if case == "missing_prediction"
            else _registry(store)
        )
        await registrar.register(seed, registered_by="Mimir")
    admission = _admission(candidate.input_manifest_digest)
    if case == "wrong_purpose":
        admission = replace(admission, purpose_id="unrelated-review")
    clock_values = iter((_AS_OF, _AS_OF, _AS_OF, _AS_OF + timedelta(hours=2)))
    registry = StateStoreEffectModelRegistry(
        store,
        clock=(lambda: next(clock_values)) if case == "admission_expires" else lambda: _AS_OF,
        feedback_source=_CurrentFixtureSource(available=case != "stale_source"),
    )
    result = await registry.rebuild_challenger(
        seed=seed,
        outcomes=(first,),
        as_of=_AS_OF,
        expected_revision=99 if case == "wrong_revision" else 1,
        admission=admission,
    )
    assert not result.accepted and result.reason == reason
    assert not any(":generation:" in key for key in store._state)  # noqa: SLF001


async def test_rebuild_rejects_a_future_cutoff() -> None:
    registry = StateStoreEffectModelRegistry(
        InMemoryStateStore(),
        clock=lambda: _AS_OF,
        feedback_source=_CurrentFixtureSource(),
    )
    with pytest.raises(ValueError, match="known source time"):
        await registry.rebuild_challenger(
            seed=_model(EffectModelStatus.CHALLENGER),
            outcomes=(),
            as_of=_AS_OF + timedelta(seconds=1),
            expected_revision=1,
            admission=_admission("a" * 64),
        )


async def test_unknown_record_without_snapshot_does_not_become_a_training_sample() -> None:
    store = InMemoryStateStore()
    seed = _model(EffectModelStatus.CHALLENGER)
    await _registry(store).register(seed, registered_by="Mimir")
    first = _feedback(1)
    unknown = ResponseOutcome.model_validate(
        {
            **_feedback(2).model_dump(),
            "prediction_snapshot": None,
            "observed_value": None,
            "observed_at": None,
            "label": "unscorable",
            "verification_status": "hold",
        }
    )
    outcomes = (first, unknown)
    candidate = rebuild_feedback(seed=seed, outcomes=outcomes, as_of=_AS_OF, complete=True)
    registry = StateStoreEffectModelRegistry(
        store,
        clock=lambda: _AS_OF,
        feedback_source=_CurrentFixtureSource(),
    )
    result = await registry.rebuild_challenger(
        seed=seed,
        outcomes=outcomes,
        as_of=_AS_OF,
        expected_revision=1,
        admission=_admission(candidate.input_manifest_digest),
    )
    assert result.accepted
    loaded = await _challenger(registry)
    assert loaded is not None and loaded.sample_count == 1
