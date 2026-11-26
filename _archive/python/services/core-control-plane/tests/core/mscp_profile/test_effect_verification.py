"""Tests for MSCP-derived deterministic effect verification."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.mscp_profile import (
    EffectVerificationReason,
    EffectVerificationStatus,
    ExpectedEffect,
    ObservedEffect,
    verify_effect,
)

_PREDICTED_AT = datetime(2026, 7, 21, tzinfo=UTC)


def _expected() -> ExpectedEffect:
    return ExpectedEffect(
        prediction_id="prediction-1",
        target_ref="resource:example",
        metric="availability",
        acceptable_min=0.99,
        acceptable_max=1.0,
        predicted_at=_PREDICTED_AT,
        observation_deadline=_PREDICTED_AT + timedelta(minutes=5),
    )


def _observed(**overrides: object) -> ObservedEffect:
    values = {
        "prediction_id": "prediction-1",
        "target_ref": "resource:example",
        "metric": "availability",
        "value": 0.995,
        "observed_at": _PREDICTED_AT + timedelta(minutes=1),
    }
    values.update(overrides)
    return ObservedEffect(**values)  # type: ignore[arg-type]


def test_effect_inside_range_is_verified() -> None:
    result = verify_effect(_expected(), _observed())
    assert result.status is EffectVerificationStatus.VERIFIED
    assert result.reason is EffectVerificationReason.WITHIN_ACCEPTABLE_RANGE


def test_effect_outside_range_is_mismatch() -> None:
    result = verify_effect(_expected(), _observed(value=0.80))
    assert result.status is EffectVerificationStatus.MISMATCH
    assert result.reason is EffectVerificationReason.VALUE_OUTSIDE_ACCEPTABLE_RANGE


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"prediction_id": "prediction-2"}, EffectVerificationReason.PREDICTION_ID_MISMATCH),
        ({"target_ref": "resource:other"}, EffectVerificationReason.TARGET_MISMATCH),
        ({"metric": "latency"}, EffectVerificationReason.METRIC_MISMATCH),
        (
            {"observed_at": _PREDICTED_AT - timedelta(seconds=1)},
            EffectVerificationReason.OBSERVATION_BEFORE_PREDICTION,
        ),
        (
            {"observed_at": _PREDICTED_AT + timedelta(minutes=6)},
            EffectVerificationReason.OBSERVATION_AFTER_DEADLINE,
        ),
    ],
)
def test_uncorrelated_or_stale_observation_holds(
    overrides: dict[str, object],
    reason: EffectVerificationReason,
) -> None:
    result = verify_effect(_expected(), _observed(**overrides))
    assert result.status is EffectVerificationStatus.HOLD
    assert result.reason is reason


def test_effect_contract_rejects_invalid_bounds_and_time() -> None:
    with pytest.raises(ValueError, match="acceptable_min"):
        ExpectedEffect(
            prediction_id="p",
            target_ref="r",
            metric="m",
            acceptable_min=2.0,
            acceptable_max=1.0,
            predicted_at=_PREDICTED_AT,
            observation_deadline=_PREDICTED_AT,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        _observed(observed_at=datetime(2026, 7, 21))


def test_effect_contract_rejects_non_finite_values() -> None:
    with pytest.raises(ValueError, match="finite"):
        _observed(value=float("nan"))
