"""Real Dynamic consumer and audit-source cursor with isolated in-memory storage."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from fdai.core.assurance_twin import EffectModel, EffectModelStatus, StateStoreEffectModelRegistry
from fdai.core.assurance_twin.model_registry import RegistryUpdate
from fdai.core.assurance_twin.prediction_evidence import retain_prediction
from fdai.core.measurement.runners import DynamicLearningRunner
from fdai.delivery.measurement.postgres_growth import (
    PostgresResponseOutcomeSource,
)
from fdai.shared.contracts.models import EffectPredictionSnapshot, ResponseOutcome
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.assurance_twin.test_feedback_reliability import _feedback as _legacy_feedback
from tests.assurance_twin.test_model_registry import _NOW, _CurrentFixtureSource
from tests.assurance_twin.test_model_registry import _model as _legacy_model


def _model(status: EffectModelStatus) -> EffectModel:
    return replace(
        _legacy_model(status),
        prediction_model_ref="effect-model@1",
        prediction_model_digest="a" * 64,
        unit="ms",
    )


def _registry(store: InMemoryStateStore) -> StateStoreEffectModelRegistry:
    return StateStoreEffectModelRegistry(
        store, clock=lambda: _NOW + timedelta(hours=1), feedback_source=_CurrentFixtureSource()
    )


def _feedback(index: int, *, action_type_id: str = "ops.scale-out") -> ResponseOutcome:
    outcome = _legacy_feedback(index)
    assert outcome.predicted_at is not None
    assert outcome.observation_deadline is not None
    snapshot = EffectPredictionSnapshot(
        prediction_id=outcome.prediction_id or "",
        event_id=outcome.event_id,
        action_id=outcome.action_id,
        action_type_id=action_type_id,
        target_digest=outcome.target_digest,
        metric=outcome.metric or "",
        unit="ms",
        objective="minimize",
        model_ref="effect-model@1",
        model_digest="a" * 64,
        source_digest="b" * 64,
        independence_key=f"{index:064x}",
        point_prediction=100.0,
        interval_lower=90.0,
        interval_upper=110.0,
        nominal_coverage=0.95,
        known_at=outcome.predicted_at,
        predicted_at=outcome.predicted_at,
        observation_deadline=outcome.observation_deadline,
    )
    return ResponseOutcome.model_validate(
        {
            **outcome.model_dump(),
            "schema_version": "1.1.0",
            "outcome_revision": 1,
            "action_type_id": action_type_id,
            "prediction_snapshot": snapshot,
            "observation_unit": "ms",
            "observation_receipt_ref": f"observation:{index}",
        }
    )


async def _retain(store: InMemoryStateStore, *outcomes: ResponseOutcome) -> None:
    for outcome in outcomes:
        assert outcome.prediction_snapshot is not None
        await retain_prediction(
            store,
            outcome.prediction_snapshot,
            recorded_at=outcome.prediction_snapshot.predicted_at,
        )


class _AuditSource(PostgresResponseOutcomeSource):
    def __init__(self, store: InMemoryStateStore, outcomes: tuple[ResponseOutcome, ...]) -> None:
        super().__init__(dsn="unused-local-fake", state_store=store)
        self._outcomes = outcomes

    async def _rows(self, after_seq: int) -> list[Mapping[str, Any]]:
        return [
            {"seq": index, "entry": outcome.model_dump(mode="json")}
            for index, outcome in enumerate(self._outcomes, start=1)
            if index > after_seq
        ]


async def test_unfinished_learner_replays_while_committed_event_is_not_learned_twice() -> None:
    store = InMemoryStateStore()
    first = _feedback(1)
    second = _feedback(2, action_type_id="ops.restart-service")
    await _retain(store, first, second)
    registry = _registry(store)
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")

    def runner() -> DynamicLearningRunner:
        return DynamicLearningRunner(
            outcome_source=_AuditSource(store, (first, second)),
            registry=_registry(store),
            audit_store=store,
            clock=lambda: _NOW + timedelta(hours=1),
        )

    with pytest.raises(RuntimeError, match="retry required: challenger_not_registered"):
        await runner().run_once()
    assert await store.read_state("measurement:dynamic_learning:watermark") == {
        "seq": 1,
        "revision": 1,
    }
    await registry.register(
        replace(_model(EffectModelStatus.CHALLENGER), action_type_id=second.action_type_id),
        registered_by="Mimir",
    )
    report = await runner().run_once()
    assert report.total_outcomes == 1
    assert report.accepted_count == 1
    assert report.reasons == (("challenger_updated", 1),)
    assert await store.read_state("measurement:dynamic_learning:watermark") == {
        "seq": 2,
        "revision": 2,
    }
    assert await store.read_state("measurement:pattern_growth:watermark") is None
    for action in (first.action_type_id, second.action_type_id):
        model = await registry.get(
            status=EffectModelStatus.CHALLENGER, action_type_id=action, metric="latency_p99_ms"
        )
        assert model is not None and model.sample_count == 1
    assert (await runner().run_once()).total_outcomes == 0


async def test_persistent_contention_does_not_advance_feedback_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    await _retain(store, _feedback(1))
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")

    async def conflict(*args: Any, **kwargs: Any) -> bool:
        return False

    with monkeypatch.context() as patch:
        patch.setattr(store, "compare_and_set_state_with_audit", conflict)
        with pytest.raises(RuntimeError, match="retry required: revision_conflict"):
            await DynamicLearningRunner(
                outcome_source=_AuditSource(store, (_feedback(1),)),
                registry=registry,
                audit_store=store,
            ).run_once()
    assert await store.read_state("measurement:dynamic_learning:watermark") is None
    assert tuple(store.audit_entries)[-1]["entry"]["reason"] == "revision_conflict"
    assert (await registry.update_from_outcome(_feedback(1))).accepted


async def test_unknown_outcome_is_audited_without_learning_or_inventing_failure() -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")
    unknown = ResponseOutcome.model_validate(
        {
            **_feedback(1).model_dump(),
            "label": "unscorable",
            "verification_status": "hold",
            "verification_reason": "observation_provider_failed",
            "observed_value": None,
            "observed_at": None,
        }
    )
    report = await DynamicLearningRunner(
        outcome_source=_AuditSource(store, (unknown,)),
        registry=registry,
        audit_store=store,
    ).run_once()
    assert report.accepted_count == 0
    assert report.reasons == (("outcome_unscorable", 1),)
    assert tuple(store.audit_entries)[-2]["entry"]["response_outcome_id"] == str(unknown.outcome_id)
    assert unknown.metric is not None
    model = await registry.get(
        status=EffectModelStatus.CHALLENGER,
        action_type_id=unknown.action_type_id,
        metric=unknown.metric,
    )
    assert model is not None and model.sample_count == 0


@pytest.mark.parametrize(
    "unavailable_reason",
    ["outcome_prediction_evidence_unavailable", "model_generation_sources_unavailable"],
)
async def test_versioned_missing_retained_prediction_is_retryable_before_ack(
    unavailable_reason: str,
) -> None:
    store = InMemoryStateStore()

    class Registry:
        available = False

        async def update_from_outcome(self, outcome: ResponseOutcome) -> RegistryUpdate:
            return RegistryUpdate(
                self.available,
                "challenger_updated" if self.available else unavailable_reason,
            )

    registry = Registry()

    def runner() -> DynamicLearningRunner:
        return DynamicLearningRunner(
            outcome_source=_AuditSource(store, (_feedback(1),)),
            registry=registry,
            audit_store=store,
        )

    with pytest.raises(RuntimeError, match=unavailable_reason):
        await runner().run_once()
    assert await store.read_state("measurement:dynamic_learning:watermark") is None
    registry.available = True
    report = await runner().run_once()
    assert report.accepted_count == 1
    assert (await store.read_state("measurement:dynamic_learning:watermark"))["seq"] == 1  # type: ignore[index]


async def test_legacy_prediction_gap_is_a_held_outcome_not_an_invented_failure() -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")
    raw = _feedback(1).model_dump(mode="json")
    for name in (
        "prediction_snapshot",
        "outcome_revision",
        "previous_revision_digest",
        "observation_unit",
        "observation_receipt_ref",
    ):
        raw.pop(name, None)
    outcome = ResponseOutcome.model_validate({**raw, "schema_version": "1.0.0"})
    report = await DynamicLearningRunner(
        outcome_source=_AuditSource(store, (outcome,)),
        registry=registry,
        audit_store=store,
    ).run_once()
    assert report.accepted_count == 0
    assert report.reasons == (("outcome_prediction_snapshot_unavailable", 1),)
    assert outcome.label.value == "mismatch"
    assert (await store.read_state("measurement:dynamic_learning:watermark"))["seq"] == 1  # type: ignore[index]


async def test_scalar_total_deadline_leaves_unfinished_source_unacknowledged() -> None:
    store = InMemoryStateStore()

    class Registry:
        async def update_from_outcome(self, outcome: ResponseOutcome) -> RegistryUpdate:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    with pytest.raises(TimeoutError):
        await DynamicLearningRunner(
            outcome_source=_AuditSource(store, (_feedback(1),)),
            registry=Registry(),
            audit_store=store,
            run_timeout_s=0.01,
        ).run_once()
    assert await store.read_state("measurement:dynamic_learning:watermark") is None


@pytest.mark.parametrize("deadline", [0, -1, float("inf"), float("nan")])
def test_scalar_rejects_unbounded_deadlines(deadline: float) -> None:
    store = InMemoryStateStore()
    with pytest.raises(ValueError, match="finite and positive"):
        DynamicLearningRunner(
            outcome_source=_AuditSource(store, ()),
            registry=_registry(store),
            audit_store=store,
            run_timeout_s=deadline,
        )
