"""Durable challenger updates without active-model self-promotion."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fdai.core.assurance_twin import (
    CausalEvidenceGrade,
    EffectModel,
    EffectModelStatus,
    StateStoreEffectModelRegistry,
)
from fdai.core.assurance_twin.prediction_evidence import retain_prediction
from fdai.shared.contracts.models import ResponseOutcome
from fdai.shared.contracts.models.effect_prediction import EffectPredictionSnapshot
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 7, 30, tzinfo=UTC)


def _snapshot(index: int | None = None) -> EffectPredictionSnapshot:
    return EffectPredictionSnapshot(
        prediction_id="prediction-1" if index is None else f"prediction-{index}",
        event_id=UUID(int=1 if index is None else index),
        action_id=UUID(int=16 if index is None else 1000 + index),
        action_type_id="ops.scale-out",
        target_digest="0" * 64,
        metric="latency_p99_ms",
        unit="ms",
        objective="minimize",
        model_ref="baseline.scale-out@1.0.0",
        model_digest="b" * 64,
        source_digest="c" * 64,
        independence_key=hashlib.sha256(f"synthetic-episode:{index}".encode()).hexdigest(),
        point_prediction=100.0,
        interval_lower=90.0,
        interval_upper=110.0,
        nominal_coverage=0.95,
        known_at=_NOW,
        predicted_at=_NOW,
        observation_deadline=_NOW + timedelta(minutes=5),
    )


class _PreparedRegistry(StateStoreEffectModelRegistry):
    """Seed actual prediction-store fixtures before any outcome is supplied."""

    async def register(self, model: EffectModel, *, registered_by: str) -> bool:
        created = await super().register(model, registered_by=registered_by)
        for snapshot in (_snapshot(), *(_snapshot(index) for index in range(1, 9))):
            await retain_prediction(self._store, snapshot, recorded_at=_NOW)
        return created


class _CurrentFixtureSource:
    """Trusted current-source result for this fixed synthetic observation corpus."""

    def __init__(self, available: bool = True) -> None:
        self.available = available
        self.requests: list[tuple[str, ...]] = []

    async def current(self, revision_digests: tuple[str, ...]) -> bool:
        self.requests.append(revision_digests)
        return self.available


def _registry(store: StateStore) -> StateStoreEffectModelRegistry:
    return _PreparedRegistry(
        store,
        clock=lambda: _NOW + timedelta(hours=1),
        feedback_source=_CurrentFixtureSource(),
    )


def _model(status: EffectModelStatus) -> EffectModel:
    return EffectModel(
        model_id="effect.ops.scale-out",
        version="1.0.0",
        revision=1,
        action_type_id="ops.scale-out",
        metric="latency_p99_ms",
        status=status,
        evidence_grade=CausalEvidenceGrade.QUASI_EXPERIMENTAL,
        causal_evidence_receipt_digest="a" * 64,
        learned_at=_NOW,
        learned_through=_NOW,
        prediction_model_ref="baseline.scale-out@1.0.0",
        prediction_model_digest="b" * 64,
        unit="ms",
    )


def _outcome() -> ResponseOutcome:
    return ResponseOutcome.model_validate(
        {
            "schema_version": "1.1.0",
            "outcome_id": "00000000-0000-0000-0000-000000000101",
            "idempotency_key": "response-outcome:example",
            "action_id": "00000000-0000-0000-0000-000000000010",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "action_type_id": "ops.scale-out",
            "target_digest": "0" * 64,
            "prediction_id": "prediction-1",
            "metric": "latency_p99_ms",
            "expected_min": 90.0,
            "expected_max": 110.0,
            "observed_value": 80.0,
            "predicted_at": _NOW,
            "observation_deadline": _NOW + timedelta(minutes=5),
            "observed_at": _NOW + timedelta(minutes=1),
            "label": "mismatch",
            "verification_status": "mismatch",
            "verification_reason": "value_outside_acceptable_range",
            "execution_mode": "enforce",
            "execution_outcome": "published",
            "rollback_succeeded": False,
            "decision": "auto",
            "evidence_refs": ["effect:prediction-1"],
            "recorded_at": _NOW + timedelta(minutes=2),
            "outcome_revision": 1,
            "prediction_snapshot": _snapshot(),
            "observation_unit": "ms",
            "observation_receipt_ref": "independent-observer:example",
        }
    )


async def test_registry_updates_only_registered_challenger() -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    active = _model(EffectModelStatus.ACTIVE)
    challenger = _model(EffectModelStatus.CHALLENGER)
    assert await registry.register(active, registered_by="Mimir") is True
    assert await registry.register(challenger, registered_by="Mimir") is True

    result = await registry.update_from_outcome(_outcome())
    loaded_active = await registry.get(
        status=EffectModelStatus.ACTIVE,
        action_type_id="ops.scale-out",
        metric="latency_p99_ms",
    )
    loaded_challenger = await registry.get(
        status=EffectModelStatus.CHALLENGER,
        action_type_id="ops.scale-out",
        metric="latency_p99_ms",
    )

    assert result.accepted is True
    assert loaded_active == active
    assert loaded_challenger is not None
    assert loaded_challenger.revision == 2
    assert loaded_challenger.bias_correction == -20.0
    action_kinds = [
        record["entry"]["action_kind"]
        for record in store.audit_entries
        if record["entry"]["action_kind"] != "dynamic.effect_prediction.frozen"
    ]
    assert action_kinds == [
        "dynamic.effect_model.registered",
        "dynamic.effect_model.registered",
        "dynamic.effect_model.challenger.updated",
    ]


async def test_registry_does_not_create_unregistered_challenger() -> None:
    store = InMemoryStateStore()
    registry = _registry(store)

    result = await registry.update_from_outcome(_outcome())

    assert result.accepted is False
    assert result.reason == "challenger_not_registered"
    assert tuple(store.audit_entries) == ()
