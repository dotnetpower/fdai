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
