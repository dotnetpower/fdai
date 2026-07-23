from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from fdai.shared.contracts.models import (
    ForecastOutcome,
    ForecastOutcomeLabel,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import (
    ContractValidationError,
    JsonSchemaContractValidator,
)

T0 = datetime(2026, 7, 1, tzinfo=UTC)


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "outcome_id": UUID(int=1),
        "idempotency_key": "forecast-outcome-1",
        "correlation_id": "corr-1",
        "prediction_id": UUID(int=2),
        "detector_id": "capacity-linear",
        "detector_version": "1.0.0",
        "access_scope_digest": "f" * 64,
        "target_digest": "a" * 64,
        "metric": "capacity_percent",
        "feature_cutoff": T0,
        "horizon_started_at": T0,
        "horizon_ended_at": T0 + timedelta(hours=1),
        "direction": "rising",
        "threshold": 90.0,
        "predicted_value": 95.0,
        "interval_lower": 91.0,
        "interval_upper": 99.0,
        "observed_value": 94.0,
        "actual_breach_at": T0 + timedelta(minutes=45),
        "label": "true_positive",
        "intervention_refs": [],
        "evidence_refs": ["metric-window:1"],
        "telemetry_completeness": "complete",
        "closed_at": T0 + timedelta(hours=2),
        "mode": "shadow",
    }
    payload.update(overrides)
    return payload


def test_registry_exposes_forecast_outcome_schema() -> None:
    schema = PackageResourceSchemaRegistry().get("forecast-outcome", "1.0.0")
    assert schema["title"] == "ForecastOutcome"


def test_forecast_outcome_accepts_grounded_true_positive() -> None:
    outcome = ForecastOutcome.model_validate(_payload())
    assert outcome.label is ForecastOutcomeLabel.TRUE_POSITIVE
    JsonSchemaContractValidator(PackageResourceSchemaRegistry()).validate(
        "forecast-outcome",
        outcome.model_dump(mode="json"),
    )


def test_false_negative_requires_no_prediction_and_actual_breach() -> None:
    outcome = ForecastOutcome.model_validate(
        _payload(
            prediction_id=None,
            label="false_negative",
            predicted_value=None,
            interval_lower=None,
            interval_upper=None,
        )
    )
    assert outcome.prediction_id is None
    with pytest.raises(ValidationError, match="unpredicted actual breach"):
        ForecastOutcome.model_validate(_payload(label="false_negative"))
    with pytest.raises(ValidationError, match="MUST NOT carry prediction evidence"):
        ForecastOutcome.model_validate(
            _payload(
                prediction_id=None,
                label="false_negative",
                interval_lower=None,
                interval_upper=None,
            )
        )


def test_unscorable_cannot_claim_complete_telemetry() -> None:
    with pytest.raises(ValidationError, match="MUST NOT claim complete telemetry"):
        ForecastOutcome.model_validate(_payload(label="unscorable", actual_breach_at=None))


def test_intervention_censored_requires_intervention_reference() -> None:
    with pytest.raises(ValidationError, match="MUST reference an intervention"):
        ForecastOutcome.model_validate(
            _payload(label="intervention_censored", actual_breach_at=None)
        )


@pytest.mark.parametrize("label", ["false_positive", "intervention_censored"])
def test_non_breach_labels_reject_actual_breach(label: str) -> None:
    overrides: dict[str, object] = {"label": label}
    if label == "intervention_censored":
        overrides["intervention_refs"] = ["action:1"]
    with pytest.raises(ValidationError, match="MUST NOT carry actual_breach_at"):
        ForecastOutcome.model_validate(_payload(**overrides))


def test_true_positive_breach_must_fall_inside_horizon() -> None:
    with pytest.raises(ValidationError, match="inside the forecast horizon"):
        ForecastOutcome.model_validate(
            _payload(actual_breach_at=T0 + timedelta(hours=1, minutes=5))
        )


def test_late_breach_must_follow_horizon() -> None:
    with pytest.raises(ValidationError, match="after the forecast horizon"):
        ForecastOutcome.model_validate(_payload(label="late_breach"))


def test_actual_breach_must_precede_close_time() -> None:
    with pytest.raises(ValidationError, match="between feature cutoff and close time"):
        ForecastOutcome.model_validate(_payload(actual_breach_at=T0 + timedelta(hours=3)))


def test_incomplete_telemetry_requires_unscorable_label() -> None:
    with pytest.raises(ValidationError, match="incomplete telemetry MUST be unscorable"):
        ForecastOutcome.model_validate(_payload(telemetry_completeness="partial"))


def test_prevented_breach_requires_intervention_censored_label() -> None:
    with pytest.raises(ValidationError, match="MUST be intervention-censored"):
        ForecastOutcome.model_validate(
            _payload(
                label="false_positive",
                actual_breach_at=None,
                intervention_refs=["action:1"],
            )
        )


def test_magnitude_error_requires_observation_outside_interval() -> None:
    with pytest.raises(ValidationError, match="outside the interval"):
        ForecastOutcome.model_validate(_payload(label="magnitude_error"))
    with pytest.raises(ValidationError, match="observation and interval"):
        ForecastOutcome.model_validate(
            _payload(
                label="magnitude_error",
                observed_value=None,
                interval_lower=None,
                interval_upper=None,
            )
        )


@pytest.mark.parametrize(
    ("actual_breach_at", "horizon_started_at"),
    [
        (T0 + timedelta(minutes=30), T0 + timedelta(minutes=45)),
        (T0 + timedelta(hours=1, microseconds=1), T0),
    ],
)
def test_magnitude_error_breach_must_fall_inside_horizon(
    actual_breach_at: datetime,
    horizon_started_at: datetime,
) -> None:
    with pytest.raises(ValidationError, match="inside the forecast horizon"):
        ForecastOutcome.model_validate(
            _payload(
                label="magnitude_error",
                actual_breach_at=actual_breach_at,
                horizon_started_at=horizon_started_at,
                observed_value=100.0,
            )
        )


@pytest.mark.parametrize(
    ("label", "missing"),
    [
        ("true_positive", "actual_breach_at"),
        ("late_breach", "actual_breach_at"),
        ("false_negative", "actual_breach_at"),
        ("intervention_censored", "intervention_refs"),
        ("magnitude_error", "observed_value"),
        ("magnitude_error", "interval_lower"),
        ("magnitude_error", "interval_upper"),
    ],
)
def test_json_schema_requires_label_specific_evidence(label: str, missing: str) -> None:
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    raw = ForecastOutcome.model_validate(_payload()).model_dump(mode="json")
    raw["label"] = label
    if label == "false_negative":
        raw.update(
            {
                "prediction_id": None,
                "predicted_value": None,
                "interval_lower": None,
                "interval_upper": None,
            }
        )
    elif label == "intervention_censored":
        raw["actual_breach_at"] = None
    elif label == "magnitude_error":
        raw["observed_value"] = 100.0
    raw.pop(missing)

    with pytest.raises(ContractValidationError):
        validator.validate("forecast-outcome", raw)


def test_json_schema_requires_prediction_id_for_predicted_outcome() -> None:
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    raw = ForecastOutcome.model_validate(_payload()).model_dump(mode="json")
    raw.pop("prediction_id")

    with pytest.raises(ContractValidationError):
        validator.validate("forecast-outcome", raw)


def test_json_schema_rejects_contradictory_terminal_labels() -> None:
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    raw = ForecastOutcome.model_validate(_payload()).model_dump(mode="json")
    raw.update({"label": "false_positive", "actual_breach_at": T0.isoformat()})
    with pytest.raises(ContractValidationError):
        validator.validate("forecast-outcome", raw)

    raw = ForecastOutcome.model_validate(_payload()).model_dump(mode="json")
    raw.update({"label": "unscorable", "actual_breach_at": None})
    with pytest.raises(ContractValidationError):
        validator.validate("forecast-outcome", raw)

    raw = ForecastOutcome.model_validate(_payload()).model_dump(mode="json")
    raw.update(
        {
            "label": "false_positive",
            "actual_breach_at": None,
            "intervention_refs": ["action:1"],
        }
    )
    with pytest.raises(ContractValidationError):
        validator.validate("forecast-outcome", raw)
