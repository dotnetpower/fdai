"""Cross-field validation for the authoritative autonomy measurement envelope."""

from copy import deepcopy

import pytest
from fdai_operator_service.autonomy_measurement_projection import (
    validate_autonomy_measurement,
)
from fdai_operator_service.families.operations import ProjectionUnavailableError


def _projection() -> dict[str, object]:
    unavailable_lower = {"value": None, "baseline": None, "direction": "lower"}
    return {
        "schema_version": "1.0.0",
        "synthetic": False,
        "window_days": 30,
        "sample_size": 1,
        "confidence": None,
        "source": {
            "name": "postgresql:operational_measurements",
            "kind": "measurement",
            "as_of": "2026-09-13T00:00:00+00:00",
        },
        "rules": {"active": 0, "candidates_30d": 0, "promoted_30d": 0},
        "success": {
            "auto_resolution_rate": {
                "value": 0.0,
                "baseline": None,
                "direction": "higher",
            },
            "human_touchpoints_per_100": unavailable_lower,
            "mttr_seconds": unavailable_lower,
            "change_lead_time_seconds": unavailable_lower,
            "cost_per_resolved_event_usd": unavailable_lower,
        },
        "metric_samples": {
            "auto_resolution_rate": 1,
            "human_touchpoints_per_100": 1,
            "mttr_seconds": 0,
            "change_lead_time_seconds": 0,
            "cost_per_resolved_event_usd": 0,
        },
        "measurement_gaps": [
            "missing_source:attributed_cost_usd",
            "missing_source:change_lead_time_seconds",
            "missing_source:mttr_seconds",
        ],
        "leading": {
            "mixed_model_disagreement_rate": unavailable_lower,
            "verifier_failure_rate": unavailable_lower,
            "shadow_divergence_rate": unavailable_lower,
        },
        "guards": [],
        "finalization": {
            "finalized_events": 0,
            "pending_events": 1,
            "adverse_events": 0,
        },
        "attribution": {
            "attributed_events": 0,
            "unattributed_events": 1,
            "coverage": 0.0,
        },
        "verticals": [
            {
                "key": "unattributed",
                "events": 1,
                "auto_resolved": 0,
                "open_risks": 1,
                "monthly_savings": 0.0,
            }
        ],
        "tier": {"mix": {"t0": 1.0}, "bands": {}},
        "trend": {},
    }


def test_accepts_auto_resolution_rate_bound_to_observed_denominator() -> None:
    projection = _projection()

    assert validate_autonomy_measurement(projection) == projection


@pytest.mark.parametrize("value", [-0.01, 0.5, 1.01])
def test_rejects_auto_resolution_rate_inconsistent_with_counts(value: float) -> None:
    projection = deepcopy(_projection())
    success = projection["success"]
    assert isinstance(success, dict)
    auto_resolution = success["auto_resolution_rate"]
    assert isinstance(auto_resolution, dict)
    auto_resolution["value"] = value

    with pytest.raises(ProjectionUnavailableError):
        validate_autonomy_measurement(projection)


@pytest.mark.parametrize(
    ("section", "metric", "field", "value"),
    [
        ("success", "mttr_seconds", "value", -1.0),
        ("success", "mttr_seconds", "direction", "higher"),
        ("leading", "verifier_failure_rate", "value", -0.01),
        ("leading", "shadow_divergence_rate", "baseline", 1.01),
        ("leading", "mixed_model_disagreement_rate", "direction", "higher"),
    ],
)
def test_rejects_metric_values_outside_their_semantic_domain(
    section: str,
    metric: str,
    field: str,
    value: object,
) -> None:
    projection = deepcopy(_projection())
    metrics = projection[section]
    assert isinstance(metrics, dict)
    measurement = metrics[metric]
    assert isinstance(measurement, dict)
    measurement[field] = value

    with pytest.raises(ProjectionUnavailableError):
        validate_autonomy_measurement(projection)


@pytest.mark.parametrize(
    ("mix", "bands"),
    [
        ({"t0": -0.1}, {}),
        ({"t0": 0.8, "t1": 0.3}, {}),
        ({"unknown": 1.0}, {}),
        ({}, {"t0": [0.8, 0.7]}),
        ({}, {"t2": [-0.1, 0.1]}),
        ({}, {"unknown": [0.0, 1.0]}),
    ],
)
def test_rejects_invalid_tier_shares_and_bands(
    mix: dict[str, float],
    bands: dict[str, list[float]],
) -> None:
    projection = deepcopy(_projection())
    tier = projection["tier"]
    assert isinstance(tier, dict)
    tier["mix"] = mix
    tier["bands"] = bands

    with pytest.raises(ProjectionUnavailableError):
        validate_autonomy_measurement(projection)


def test_rejects_numeric_overflow_as_projection_unavailable() -> None:
    projection = deepcopy(_projection())
    leading = projection["leading"]
    assert isinstance(leading, dict)
    verifier = leading["verifier_failure_rate"]
    assert isinstance(verifier, dict)
    verifier["value"] = 10**10_000

    with pytest.raises(ProjectionUnavailableError):
        validate_autonomy_measurement(projection)


def test_rejects_metric_value_without_a_metric_sample() -> None:
    projection = deepcopy(_projection())
    success = projection["success"]
    samples = projection["metric_samples"]
    assert isinstance(success, dict)
    assert isinstance(samples, dict)
    mttr = success["mttr_seconds"]
    assert isinstance(mttr, dict)
    mttr["value"] = 30.0
    samples["mttr_seconds"] = 0

    with pytest.raises(ProjectionUnavailableError):
        validate_autonomy_measurement(projection)


@pytest.mark.parametrize(
    "gap",
    [
        "missing_source:unknown",
        "unknown:mttr_seconds",
        "missing_source",
        "",
    ],
)
def test_rejects_unknown_measurement_gap(gap: str) -> None:
    projection = deepcopy(_projection())
    projection["measurement_gaps"] = [gap]

    with pytest.raises(ProjectionUnavailableError):
        validate_autonomy_measurement(projection)
