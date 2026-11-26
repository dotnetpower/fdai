"""Frozen point predictions are not acceptable ranges or self-issued outcome labels."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta, timezone

import pytest
from fdai.core.assurance_twin import (
    EffectModelStatus,
    StateStoreEffectModelRegistry,
    update_challenger,
)
from fdai.core.assurance_twin.prediction_evidence import prediction_available, retain_prediction
from fdai.shared.contracts.models import ResponseOutcome
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import JsonSchemaContractValidator
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.assurance_twin.test_feedback_reliability import _feedback
from tests.assurance_twin.test_model_registry import _NOW, _model, _snapshot


def test_versioned_schema_roundtrip_preserves_frozen_prediction() -> None:
    outcome = _feedback(1)
    payload = outcome.model_dump(mode="json", exclude_none=True)
    JsonSchemaContractValidator(PackageResourceSchemaRegistry()).validate(
        "response-outcome", payload
    )
    assert ResponseOutcome.model_validate(payload) == outcome
    assert ResponseOutcome.model_validate_json(outcome.model_dump_json()).revision_digest == (
        outcome.revision_digest
    )


def test_legacy_wire_shape_remains_unchanged_and_cannot_claim_new_provenance() -> None:
    payload = _feedback(1).model_dump()
    for name in (
        "outcome_revision",
        "previous_revision_digest",
        "prediction_snapshot",
        "observation_unit",
        "observation_receipt_ref",
    ):
        payload.pop(name)
    payload["schema_version"] = "1.0.0"
    legacy = ResponseOutcome.model_validate(payload)
    assert "outcome_revision" not in legacy.model_dump()
    assert "prediction_snapshot" not in legacy.model_dump()
    result = update_challenger(_model(EffectModelStatus.CHALLENGER), legacy)
    assert result.reason == "outcome_prediction_snapshot_unavailable"


def test_acceptable_range_midpoint_is_never_a_point_prediction() -> None:
    snapshot = _snapshot(1).model_copy(
        update={"point_prediction": 80.0, "interval_lower": 70.0, "interval_upper": 90.0}
    )
    outcome = ResponseOutcome.model_validate(
        {
            **_feedback(1).model_dump(),
            "expected_min": 0.0,
            "expected_max": 100.0,
            "prediction_snapshot": snapshot,
            "observed_value": 80.0,
            "label": "verified",
            "verification_status": "verified",
        }
    )
    update = update_challenger(_model(EffectModelStatus.CHALLENGER), outcome)
    assert update.accepted and update.model.bias_correction == 0.0
    assert update.model.mean_absolute_error == 0.0


async def test_retained_prediction_identity_cannot_be_rewritten() -> None:
    store = InMemoryStateStore()
    snapshot = _snapshot(1)
    await retain_prediction(store, snapshot, recorded_at=_NOW)
    await retain_prediction(store, snapshot, recorded_at=_NOW + timedelta(seconds=1))
    with pytest.raises(ValueError, match="prediction conflicts"):
        await retain_prediction(
            store, snapshot.model_copy(update={"point_prediction": 95.0}), recorded_at=_NOW
        )
    assert await prediction_available(store, snapshot, observed_at=_NOW + timedelta(minutes=1))
    assert not await prediction_available(store, snapshot, observed_at=_NOW - timedelta(seconds=1))
    assert await store.verify_chain()


async def test_shape_valid_feedback_without_prior_prediction_is_not_learned() -> None:
    store = InMemoryStateStore()
    registry = StateStoreEffectModelRegistry(store, clock=lambda: _NOW + timedelta(hours=1))
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")
    result = await registry.update_from_outcome(_feedback(1))
    assert not result.accepted and result.reason == "outcome_prediction_evidence_unavailable"
    assert await registry.get(
        status=EffectModelStatus.CHALLENGER, action_type_id="ops.scale-out", metric="latency_p99_ms"
    ) == _model(EffectModelStatus.CHALLENGER)


@pytest.mark.parametrize(
    "change",
    [
        {"observation_unit": "s"},
        {"observation_receipt_ref": None},
    ],
)
def test_incomparable_or_unattributed_observation_cannot_calibrate(
    change: dict[str, object],
) -> None:
    outcome = ResponseOutcome.model_validate({**_feedback(1).model_dump(), **change})
    result = update_challenger(_model(EffectModelStatus.CHALLENGER), outcome)
    assert not result.accepted and result.reason == "outcome_prediction_provenance_mismatch"


def test_changed_predictor_cannot_update_another_models_calibration() -> None:
    model = replace(_model(EffectModelStatus.CHALLENGER), prediction_model_digest="d" * 64)
    assert update_challenger(model, _feedback(1)).reason == "outcome_prediction_provenance_mismatch"


def test_equivalent_timezone_encoding_preserves_revision_identity() -> None:
    outcome = _feedback(1)
    payload = outcome.model_dump(mode="json")
    offset = timezone(timedelta(hours=9))
    for field in ("predicted_at", "observation_deadline", "observed_at", "recorded_at"):
        value = getattr(outcome, field)
        if value is not None:
            payload[field] = value.astimezone(offset).isoformat()
    snapshot = payload["prediction_snapshot"]
    for field in ("known_at", "predicted_at", "observation_deadline"):
        snapshot[field] = getattr(outcome.prediction_snapshot, field).astimezone(offset).isoformat()
    reencoded = ResponseOutcome.model_validate(payload)
    assert reencoded.revision_digest == outcome.revision_digest


@pytest.mark.parametrize("value", [True, False])
def test_boolean_measurements_are_not_numeric_outcomes(value: bool) -> None:
    with pytest.raises(ValueError, match="MUST NOT be boolean"):
        ResponseOutcome.model_validate({**_feedback(1).model_dump(), "observed_value": value})
