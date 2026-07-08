"""SeasonalAnomalyDetector - phase-aware baseline over the base detector.

Covers the seasonality contract added to observability-and-detection.md
section 2: a metric with a periodic shape is compared only against past
samples in the same seasonal phase, so a normal per-phase peak does not
fire, but an in-phase deviation still does. Per-phase cold-start is
independent, and a finding still normalizes to a shadow-mode Event.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.detection import (
    MetricSample,
    SeasonalAnomalyDetector,
)
from fdai.shared.contracts.models import Mode


def _detector(**kwargs: object) -> SeasonalAnomalyDetector:
    params: dict[str, object] = {
        "detector_id": "seasonal-1",
        "phase": "hour_of_day",
        "min_samples_per_phase": 5,
        "z_threshold": 3.0,
    }
    params.update(kwargs)
    return SeasonalAnomalyDetector(**params)  # type: ignore[arg-type]


def _hourly(values_by_hour: dict[int, list[float]]) -> list[MetricSample]:
    """Build samples: each value placed at a distinct day but fixed hour."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    out: list[MetricSample] = []
    for hour, values in values_by_hour.items():
        for day, value in enumerate(values):
            out.append(MetricSample(timestamp=base + timedelta(days=day, hours=hour), value=value))
    return out


def test_periodic_peak_is_not_anomalous_within_its_phase() -> None:
    """A high value at hour 9 is normal when hour-9 history is also high."""
    det = _detector()
    # Hour 9 baseline is high (~100); hour 3 baseline is low (~10).
    history = _hourly({9: [98, 100, 102, 99, 101], 3: [9, 10, 11, 10, 10]})
    observed = MetricSample(timestamp=datetime(2026, 1, 10, 9, tzinfo=UTC), value=100.0)
    assert (
        det.evaluate(
            metric="rps",
            resource_ref="svc-1",
            history=history,
            observed=observed,
            window_bucket="w",
        )
        is None
    )


def test_flat_baseline_ignores_other_phases() -> None:
    """A hour-9 value of 100 IS anomalous against a low hour-3 baseline...

    ...but the seasonal detector only compares within hour 9, so a value
    that matches the hour-9 baseline stays silent even though it would
    fire against the pooled 24h mean.
    """
    det = _detector()
    history = _hourly({9: [100, 100, 100, 100, 100], 3: [10, 10, 10, 10, 10]})
    # Observed at hour 3, value 10 -> matches hour-3 baseline -> no finding.
    observed = MetricSample(timestamp=datetime(2026, 1, 20, 3, tzinfo=UTC), value=10.0)
    assert (
        det.evaluate(
            metric="rps",
            resource_ref="svc-1",
            history=history,
            observed=observed,
            window_bucket="w",
        )
        is None
    )


def test_in_phase_deviation_fires() -> None:
    det = _detector()
    history = _hourly({9: [98, 100, 102, 99, 101]})  # hour-9 mean ~100
    observed = MetricSample(timestamp=datetime(2026, 1, 10, 9, tzinfo=UTC), value=500.0)
    finding = det.evaluate(
        metric="rps",
        resource_ref="svc-1",
        history=history,
        observed=observed,
        window_bucket="w",
    )
    assert finding is not None
    assert finding.direction == "over"
    assert "hour_of_day=9" in finding.window_bucket


def test_per_phase_cold_start_abstains() -> None:
    """A thin phase abstains even when other phases are well-populated."""
    det = _detector(min_samples_per_phase=5)
    # Hour 9 has 5 samples; hour 14 has only 2 -> hour-14 observation abstains.
    history = _hourly({9: [98, 100, 102, 99, 101], 14: [50, 52]})
    observed = MetricSample(timestamp=datetime(2026, 1, 10, 14, tzinfo=UTC), value=900.0)
    assert (
        det.evaluate(
            metric="rps",
            resource_ref="svc-1",
            history=history,
            observed=observed,
            window_bucket="w",
        )
        is None
    )


def test_finding_normalizes_to_shadow_event() -> None:
    det = _detector()
    history = _hourly({9: [98, 100, 102, 99, 101]})
    observed = MetricSample(timestamp=datetime(2026, 1, 10, 9, tzinfo=UTC), value=500.0)
    finding = det.evaluate(
        metric="rps",
        resource_ref="svc-1",
        history=history,
        observed=observed,
        window_bucket="w",
    )
    assert finding is not None
    event = det.to_event(finding)
    assert event.mode is Mode.SHADOW
    assert event.event_type == "anomaly.finding"
    assert event.idempotency_key == finding.idempotency_key


def test_day_of_week_phase() -> None:
    det = _detector(phase="day_of_week", min_samples_per_phase=3)
    base = datetime(2026, 1, 5, tzinfo=UTC)  # Monday
    # Mondays high, sampled weekly.
    history = [
        MetricSample(timestamp=base + timedelta(weeks=w), value=v)
        for w, v in enumerate([200, 205, 198, 202])
    ]
    observed = MetricSample(timestamp=base + timedelta(weeks=5), value=201.0)
    assert (
        det.evaluate(
            metric="rps",
            resource_ref="svc-1",
            history=history,
            observed=observed,
            window_bucket="w",
        )
        is None
    )


def test_unknown_phase_rejected() -> None:
    with pytest.raises(ValueError, match="unknown seasonal phase"):
        SeasonalAnomalyDetector(detector_id="d", phase="fortnight")


def test_min_samples_per_phase_below_two_is_rejected() -> None:
    with pytest.raises(ValueError, match="min_samples_per_phase MUST be >= 2"):
        SeasonalAnomalyDetector(detector_id="d", min_samples_per_phase=1)
