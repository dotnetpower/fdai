"""Durable challenger updates without active-model self-promotion."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.assurance_twin import (
    CausalEvidenceGrade,
    EffectModel,
    EffectModelStatus,
    StateStoreEffectModelRegistry,
)
from fdai.shared.contracts.models import ResponseOutcome
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 7, 30, tzinfo=UTC)


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
    )


def _outcome() -> ResponseOutcome:
    return ResponseOutcome.model_validate(
        {
            "schema_version": "1.0.0",
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
            "execution_mode": "shadow",
            "execution_outcome": "published",
            "decision": "auto",
            "evidence_refs": ["effect:prediction-1"],
            "recorded_at": _NOW + timedelta(minutes=2),
        }
    )


async def test_registry_updates_only_registered_challenger() -> None:
    store = InMemoryStateStore()
    registry = StateStoreEffectModelRegistry(store)
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
    action_kinds = [record["entry"]["action_kind"] for record in store.audit_entries]
    assert action_kinds == [
        "dynamic.effect_model.registered",
        "dynamic.effect_model.registered",
        "dynamic.effect_model.challenger.updated",
    ]


async def test_registry_does_not_create_unregistered_challenger() -> None:
    store = InMemoryStateStore()
    registry = StateStoreEffectModelRegistry(store)

    result = await registry.update_from_outcome(_outcome())

    assert result.accepted is False
    assert result.reason == "challenger_not_registered"
    assert tuple(store.audit_entries) == ()
