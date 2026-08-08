"""LinearForecastDetector - trend extrapolation, breach ETA, lead time.

Covers the observability-and-detection.md section 3 contract:
cold-start abstain, weak-fit abstain, rising/falling breach projection
within the horizon, already-breached and beyond-horizon silence,
severity from imminence, deterministic idempotency, and that a forecast
normalizes to an Event that re-enters event-ingest.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.detection import (
    ForecastFinding,
    LinearForecastDetector,
    MetricSample,
)
from fdai.core.detection.forecast import ForecastDetectorDecision
from fdai.core.event_ingest import EventIngest
from fdai.shared.contracts.models import Category, Mode, Severity
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import (
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)

_T0 = datetime(2026, 7, 8, tzinfo=UTC)


def _series(values: list[float]) -> list[MetricSample]:
    return [
        MetricSample(timestamp=_T0 + timedelta(seconds=i), value=v) for i, v in enumerate(values)
    ]


def _detector(**kwargs: object) -> LinearForecastDetector:
    params: dict[str, object] = {
        "detector_id": "f1",
        "threshold": 20.0,
        "horizon_seconds": 100.0,
        "min_samples": 5,
        "min_r_squared": 0.5,
    }
    params.update(kwargs)
    return LinearForecastDetector(**params)  # type: ignore[arg-type]


def _evaluate(detector: LinearForecastDetector, values: list[float]) -> ForecastFinding | None:
    return detector.evaluate(
        metric="disk_used_pct",
        resource_ref="resource:example/rg/vol-a",
        history=_series(values),
        window_bucket="2026-07-08T09:00",
    )


def test_rising_breach_within_horizon() -> None:
    # value == t (slope 1, intercept 0); threshold 20 crosses at t=20, x_last=9.
    finding = _evaluate(_detector(), list(range(10)))
    assert finding is not None
    assert finding.direction == "rising"
    assert finding.lead_time_seconds == pytest.approx(11.0, abs=1e-6)
    assert finding.r_squared == pytest.approx(1.0, abs=1e-9)
    assert finding.value_now == pytest.approx(9.0)
    assert finding.category is Category.RELIABILITY


def test_falling_breach_within_horizon() -> None:
    # value == 100 - t; threshold 50 crosses at t=50, x_last=9 -> lead 41.
    detector = _detector(threshold=50.0, direction="falling")
    finding = _evaluate(detector, [100.0 - i for i in range(10)])
    assert finding is not None
    assert finding.direction == "falling"
    assert finding.lead_time_seconds == pytest.approx(41.0, abs=1e-6)


def test_flat_trend_no_finding() -> None:
    assert _evaluate(_detector(), [5.0] * 10) is None


def test_cold_start_abstains() -> None:
    assert _evaluate(_detector(), [0.0, 1.0]) is None


def test_breach_beyond_horizon_is_silent() -> None:
    # slope 1; threshold 200 crosses at t=200, lead 191 > horizon 100.
    assert _evaluate(_detector(threshold=200.0), list(range(10))) is None


def test_already_breached_is_left_to_anomaly() -> None:
    # value_now = 9 already exceeds threshold 5 -> forecasting stays silent.
    assert _evaluate(_detector(threshold=5.0), list(range(10))) is None


def test_weak_fit_abstains() -> None:
    # A noisy series whose R-squared is below a strict floor must abstain.
    detector = _detector(min_r_squared=1.0)
    assert _evaluate(detector, [0, 1, 2, 3, 4, 5, 6, 7, 8, 10]) is None


def test_wrong_direction_is_silent() -> None:
    # A rising detector fed a falling series projects no upward breach.
    assert _evaluate(_detector(direction="rising"), [100.0 - i for i in range(10)]) is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_history_abstains(bad: float) -> None:
    # A non-finite sample makes the least-squares fit NaN; every abstain guard
    # (r_squared < min, lead <= 0, lead > horizon) is then a NaN comparison
    # that is always False, so the detector would emit an all-NaN forecast.
    # It must abstain (fail-closed) instead.
    poisoned = [0.0, 1.0, 2.0, bad, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
    assert _evaluate(_detector(), poisoned) is None


def test_explicit_evaluation_distinguishes_abstain_from_negative() -> None:
    detector = _detector()
    abstained = detector.evaluate_result(
        metric="disk_used_pct",
        resource_ref="resource:example/rg/vol-a",
        history=_series([1.0, 2.0]),
        window_bucket="2026-07-08T09:00",
    )
    negative = detector.evaluate_result(
        metric="disk_used_pct",
        resource_ref="resource:example/rg/vol-a",
        history=_series([1.0] * 10),
        window_bucket="2026-07-08T09:00",
    )
    assert abstained.decision is ForecastDetectorDecision.ABSTAINED
    assert abstained.reason == "insufficient_samples"
    assert negative.decision is ForecastDetectorDecision.PREDICTED_NO_BREACH


@pytest.mark.parametrize(
    ("threshold", "expected"),
    [
        (20.0, Severity.CRITICAL),  # lead 11 / 100 = 0.11
        (49.0, Severity.HIGH),  # lead 40 / 100 = 0.40
        (80.0, Severity.MEDIUM),  # lead 71 / 100 = 0.71
    ],
)
def test_severity_scales_with_imminence(threshold: float, expected: Severity) -> None:
    finding = _evaluate(_detector(threshold=threshold), list(range(10)))
    assert finding is not None
    assert finding.severity is expected


def test_idempotency_key_is_deterministic() -> None:
    detector = _detector()
    a = _evaluate(detector, list(range(10)))
    b = _evaluate(detector, [v * 1.0 for v in range(10)])
    assert a is not None and b is not None
    assert a.idempotency_key == b.idempotency_key


def test_category_is_configurable() -> None:
    finding = _evaluate(_detector(category=Category.COST), list(range(10)))
    assert finding is not None
    assert finding.category is Category.COST


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"detector_id": ""}, "detector_id"),
        ({"direction": "sideways"}, "direction"),
        ({"horizon_seconds": 0.0}, "horizon_seconds"),
        ({"min_samples": 1}, "min_samples"),
        ({"min_r_squared": 1.5}, "min_r_squared"),
    ],
)
def test_constructor_validates(kwargs: dict[str, object], match: str) -> None:
    base: dict[str, object] = {
        "detector_id": "f1",
        "threshold": 20.0,
        "horizon_seconds": 100.0,
    }
    base.update(kwargs)
    with pytest.raises(ValueError, match=match):
        LinearForecastDetector(**base)  # type: ignore[arg-type]


def test_to_event_defaults_to_shadow_and_carries_context() -> None:
    detector = _detector()
    finding = _evaluate(detector, list(range(10)))
    assert finding is not None
    event = detector.to_event(finding)
    assert event.event_type == "forecast.finding"
    assert event.mode is Mode.SHADOW
    assert event.idempotency_key == finding.idempotency_key
    assert event.resource_ref == "resource:example/rg/vol-a"
    assert event.payload["direction"] == "rising"
    assert event.payload["lead_time_seconds"] == pytest.approx(11.0, abs=1e-6)


def test_finding_event_re_enters_event_ingest() -> None:
    detector = _detector()
    finding = _evaluate(detector, list(range(10)))
    assert finding is not None
    validator = JsonSchemaEventValidator(
        JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    )
    ingest = EventIngest(validator=validator)

    event = detector.to_event(finding)
    ingested = ingest.ingest(event)
    assert ingested is not None
    assert ingested.event_type == "forecast.finding"
    # Re-delivery of the same forecast dedupes on the stable key.
    assert ingest.ingest(detector.to_event(finding)) is None
