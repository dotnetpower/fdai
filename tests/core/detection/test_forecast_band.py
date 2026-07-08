"""Forecast prediction-interval band - #8 false-positive suppression.

Verifies the band widens with residual spread and horizon distance, only
calls a breach "confident" when the pessimistic edge still crosses, and
never manufactures a breach the point forecast did not predict.
"""

from __future__ import annotations

import pytest

from fdai.core.detection import ForecastFinding, prediction_band
from fdai.shared.contracts.models import Category, Severity


def _finding(
    *,
    direction: str = "rising",
    projected: float = 110.0,
    threshold: float = 100.0,
    residual_std: float = 2.0,
    horizon_seconds: float = 3600.0,
    lead_time_seconds: float = 1800.0,
) -> ForecastFinding:
    return ForecastFinding(
        detector_id="det-1",
        metric="cpu.util",
        resource_ref="res-a",
        window_bucket="2026-07-07T12",
        slope_per_second=0.01,
        intercept=50.0,
        r_squared=0.95,
        residual_std=residual_std,
        horizon_seconds=horizon_seconds,
        threshold=threshold,
        direction=direction,
        value_now=80.0,
        projected_at_horizon=projected,
        lead_time_seconds=lead_time_seconds,
        category=Category.RELIABILITY,
        severity=Severity.MEDIUM,
        idempotency_key="det-1|cpu.util|2026-07-07T12",
        reason="rising trend crosses threshold",
    )


# ---------------------------------------------------------------------------
# Confident vs not-confident
# ---------------------------------------------------------------------------


def test_tight_residual_yields_confident_rising_breach() -> None:
    # projected 110, threshold 100, tiny noise -> lower edge stays above 100.
    band = prediction_band(_finding(residual_std=1.0), confidence_level="0.90")
    assert band.confident_breach is True
    assert band.lower > 100.0


def test_wide_residual_suppresses_rising_breach() -> None:
    # Same point breach, but large noise pulls the lower edge below 100.
    band = prediction_band(_finding(residual_std=20.0), confidence_level="0.90")
    assert band.confident_breach is False
    assert band.lower < 100.0


def test_falling_breach_uses_upper_edge() -> None:
    # Falling toward a floor threshold of 100; projected 90 (breached point).
    band = prediction_band(
        _finding(direction="falling", projected=90.0, threshold=100.0, residual_std=1.0),
        confidence_level="0.90",
    )
    assert band.confident_breach is True
    assert band.upper < 100.0


def test_falling_breach_suppressed_by_noise() -> None:
    band = prediction_band(
        _finding(direction="falling", projected=90.0, threshold=100.0, residual_std=20.0),
        confidence_level="0.90",
    )
    assert band.confident_breach is False
    assert band.upper > 100.0


# ---------------------------------------------------------------------------
# Band geometry
# ---------------------------------------------------------------------------


def test_band_is_symmetric_around_projection() -> None:
    band = prediction_band(_finding(), confidence_level="0.95")
    assert band.center == 110.0
    assert band.upper - band.center == pytest.approx(band.center - band.lower)
    assert band.half_width > 0.0


def test_half_width_grows_with_horizon_distance() -> None:
    near = prediction_band(_finding(lead_time_seconds=1.0), confidence_level="0.90")
    far = prediction_band(_finding(lead_time_seconds=3600.0), confidence_level="0.90")
    # Farther projection -> wider band (growth factor rises with lead fraction).
    assert far.half_width > near.half_width


def test_higher_confidence_widens_band() -> None:
    lo = prediction_band(_finding(), confidence_level="0.80")
    hi = prediction_band(_finding(), confidence_level="0.99")
    assert hi.half_width > lo.half_width


def test_zero_residual_is_always_confident() -> None:
    # A perfect fit collapses the band to the point estimate.
    band = prediction_band(_finding(residual_std=0.0), confidence_level="0.99")
    assert band.half_width == 0.0
    assert band.confident_breach is True


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_unknown_confidence_level_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported confidence_level"):
        prediction_band(_finding(), confidence_level="0.925")


def test_zero_horizon_does_not_divide_by_zero() -> None:
    band = prediction_band(
        _finding(horizon_seconds=0.0, lead_time_seconds=0.0), confidence_level="0.90"
    )
    # growth collapses to 1.0; still a valid band.
    assert band.half_width >= 0.0


# ---------------------------------------------------------------------------
# Hardening: corrupt-fit defenses (rubric critique)
# ---------------------------------------------------------------------------


def test_negative_residual_std_does_not_invert_band() -> None:
    """A negative std must not flip the band into an over-confident breach."""
    # projected 110, threshold 100. With residual magnitude 20 the lower
    # edge should drop below 100 -> NOT confident. A naive negative std
    # would instead push the lower edge up and falsely confirm.
    band = prediction_band(_finding(residual_std=-20.0), confidence_level="0.90")
    assert band.half_width > 0.0  # magnitude taken, not the raw negative
    assert band.confident_breach is False
    assert band.lower < 100.0


def test_non_finite_residual_std_is_never_confident() -> None:
    band = prediction_band(_finding(residual_std=float("inf")), confidence_level="0.90")
    assert band.confident_breach is False


def test_nan_residual_std_is_never_confident() -> None:
    band = prediction_band(_finding(residual_std=float("nan")), confidence_level="0.90")
    assert band.confident_breach is False


def test_invalid_direction_is_rejected() -> None:
    with pytest.raises(ValueError, match="direction MUST be"):
        prediction_band(_finding(direction="sideways"), confidence_level="0.90")
