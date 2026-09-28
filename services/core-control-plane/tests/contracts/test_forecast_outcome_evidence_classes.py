"""ForecastOutcome 1.2.0 names an independent-evidence class and cites its rejection record."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fdai.core.detection.forecast_outcome import forecast_outcome_schema_version
from fdai.shared.contracts.models import ForecastOutcome, ForecastScoringExclusion
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import (
    ContractValidationError,
    JsonSchemaContractValidator,
)
from pydantic import ValidationError

T0 = datetime(2026, 7, 1, tzinfo=UTC)
REFERENCE = "operational-evidence-rejection:sha256:" + "9" * 64


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.2.0",
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
        "observed_value": 70.0,
        "label": "unscorable",
        "intervention_refs": [],
        "evidence_refs": ["metric-window:1", REFERENCE],
        "telemetry_completeness": "complete",
        "closed_at": T0 + timedelta(hours=2),
        "mode": "shadow",
        "scoring_exclusions": ["operational_evidence_conflicting"],
    }
    payload.update(overrides)
    return payload


def _raw(**overrides: object) -> dict[str, object]:
    """Return a JSON payload that bypasses the model so the schema is tested on its own."""
    raw = ForecastOutcome.model_validate(_payload()).model_dump(mode="json")
    raw.update(overrides)
    return raw


def test_every_evidence_class_is_versioned_and_cited() -> None:
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    classes = [item for item in ForecastScoringExclusion if item.startswith("operational_")]
    assert len(classes) == 7
    for exclusion in classes:
        outcome = ForecastOutcome.model_validate(_payload(scoring_exclusions=[exclusion.value]))
        assert forecast_outcome_schema_version(outcome.scoring_exclusions) == "1.2.0"
        validator.validate("forecast-outcome", outcome.model_dump(mode="json"))
    assert forecast_outcome_schema_version(["excluded_window"]) == "1.1.0"
    assert forecast_outcome_schema_version([]) == "1.0.0"


@pytest.mark.parametrize(
    "overrides",
    [
        {"schema_version": "1.1.0"},
        {"evidence_refs": ["metric-window:1"]},
        {"evidence_refs": ["metric-window:1", REFERENCE, REFERENCE.replace("9", "8")]},
        {"evidence_refs": ["metric-window:1", "operational-evidence-rejection:forged"]},
        {"scoring_exclusions": ["excluded_window"]},
        {
            "scoring_exclusions": [
                "operational_evidence_conflicting",
                "operational_evidence_stale",
            ]
        },
        {"label": "false_positive", "scoring_exclusions": []},
    ],
)
def test_model_and_schema_refuse_an_uncited_or_misversioned_class(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ForecastOutcome.model_validate(_payload(**overrides))
    with pytest.raises(ContractValidationError):
        JsonSchemaContractValidator(PackageResourceSchemaRegistry()).validate(
            "forecast-outcome", _raw(**overrides)
        )


def test_earlier_versions_keep_their_shape() -> None:
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    legacy = ForecastOutcome.model_validate(
        _payload(
            schema_version="1.1.0",
            scoring_exclusions=["intervention_history_unavailable"],
            evidence_refs=["metric-window:1"],
        )
    )
    validator.validate("forecast-outcome", legacy.model_dump(mode="json"))
    with pytest.raises(ContractValidationError):
        validator.validate(
            "forecast-outcome",
            {
                **legacy.model_dump(mode="json"),
                "scoring_exclusions": ["operational_evidence_stale"],
            },
        )
