"""ResponseOutcome model and JSON Schema parity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.shared.contracts.models import ResponseOutcome
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import JsonSchemaContractValidator
from pydantic import ValidationError

_NOW = datetime(2026, 7, 30, tzinfo=UTC)


def _payload(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "schema_version": "1.0.0",
        "outcome_id": "00000000-0000-0000-0000-000000000101",
        "idempotency_key": "response-outcome:example",
        "action_id": "00000000-0000-0000-0000-000000000010",
        "event_id": "00000000-0000-0000-0000-000000000001",
        "action_type_id": "ops.scale-out",
        "target_digest": "0" * 64,
        "prediction_id": "prediction-1",
        "metric": "availability",
        "expected_min": 0.99,
        "expected_max": 1.0,
        "observed_value": 0.995,
        "predicted_at": _NOW,
        "observation_deadline": _NOW + timedelta(minutes=5),
        "observed_at": _NOW + timedelta(minutes=1),
        "label": "verified",
        "verification_status": "verified",
        "verification_reason": "within_acceptable_range",
        "execution_mode": "shadow",
        "execution_outcome": "published",
        "decision": "auto",
        "rollback_succeeded": None,
        "evidence_refs": ["effect:prediction-1"],
        "recorded_at": _NOW + timedelta(minutes=2),
    }
    values.update(overrides)
    return values


def test_response_outcome_round_trips_through_json_schema() -> None:
    outcome = ResponseOutcome.model_validate(_payload())

    JsonSchemaContractValidator(PackageResourceSchemaRegistry()).validate(
        "response-outcome",
        outcome.model_dump(mode="json", exclude_none=True),
    )
    assert outcome.scorable is True
    assert outcome.verification_passed is True


def test_unscorable_outcome_must_hold_and_carry_no_partial_observation() -> None:
    outcome = ResponseOutcome.model_validate(
        _payload(
            prediction_id=None,
            metric=None,
            expected_min=None,
            expected_max=None,
            observed_value=None,
            predicted_at=None,
            observation_deadline=None,
            observed_at=None,
            label="unscorable",
            verification_status="hold",
            verification_reason="prediction_unavailable",
        )
    )

    assert outcome.scorable is False
    assert outcome.verification_passed is False


def test_observation_outside_effect_window_is_rejected() -> None:
    with pytest.raises(ValidationError, match="inside its effect window"):
        ResponseOutcome.model_validate(_payload(observed_at=_NOW + timedelta(minutes=6)))
