"""MetricAnomalyDetector - deterministic z-score detection + finding re-entry.

Covers the observability-and-detection.md section 2 contract:
cold-start abstain, within-threshold silence, over/under detection,
flat-baseline safety, severity-from-magnitude, deterministic
idempotency, and that a finding normalizes to an Event that re-enters
event-ingest.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from fdai.core.detection import (
    MetricAnomalyDetector,
    MetricSample,
)
from fdai.core.event_ingest import EventIngest
from fdai.shared.contracts.models import Category, Mode, Severity
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import (
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)

_T = datetime(2026, 7, 8, tzinfo=UTC)
_STD = math.sqrt(2.0)  # pstdev([8,9,10,11,12]) == sqrt(2); mean == 10
_BASE = [8.0, 9.0, 10.0, 11.0, 12.0]


def _history(values: list[float]) -> list[MetricSample]:
    return [MetricSample(timestamp=_T, value=v) for v in values]


def _detector(**kwargs: object) -> MetricAnomalyDetector:
    params: dict[str, object] = {
        "detector_id": "d1",
        "min_samples": 5,
        "z_threshold": 3.0,
    }
    params.update(kwargs)
    return MetricAnomalyDetector(**params)  # type: ignore[arg-type]


def _evaluate(
    detector: MetricAnomalyDetector, observed: float, *, values: list[float] | None = None
):
    return detector.evaluate(
        metric="cpu_pct",
        resource_ref="resource:example/rg/vm-a",
        history=_history(values if values is not None else _BASE),
        observed=MetricSample(timestamp=_T, value=observed),
        window_bucket="2026-07-08T09:00",
    )


def test_cold_start_abstains() -> None:
    # Only two samples, min_samples=5 -> no finding.
    result = _evaluate(_detector(), 100.0, values=[10.0, 10.0])
    assert result is None


def test_within_threshold_is_silent() -> None:
    # z ~= 0.71 for observed=11 against mean 10, std sqrt(2).
    assert _evaluate(_detector(), 11.0) is None


def test_over_anomaly_is_detected() -> None:
    observed = 10.0 + 4.5 * _STD  # z == 4.5 (off the severity boundary)
    finding = _evaluate(_detector(), observed)
    assert finding is not None
    assert finding.direction == "over"
    assert finding.z_score == pytest.approx(4.5, abs=1e-6)
    assert finding.category is Category.RELIABILITY
    assert finding.severity is Severity.HIGH
    assert finding.baseline_mean == pytest.approx(10.0)


def test_under_anomaly_is_detected() -> None:
    observed = 10.0 - 4.5 * _STD
    finding = _evaluate(_detector(), observed)
    assert finding is not None
    assert finding.direction == "under"
    assert finding.z_score == pytest.approx(4.5, abs=1e-6)


def test_flat_baseline_same_value_is_silent() -> None:
    assert _evaluate(_detector(), 10.0, values=[10.0] * 5) is None


def test_flat_baseline_deviation_is_critical() -> None:
    finding = _evaluate(_detector(), 15.0, values=[10.0] * 5)
    assert finding is not None
    assert finding.z_score is None
    assert finding.severity is Severity.CRITICAL
    assert finding.direction == "over"
    assert finding.reason == "flat_baseline_deviation"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_observed_abstains(bad: float) -> None:
    # A NaN observed slips past ``abs(z) < threshold`` (NaN comparisons are
    # always False) and would FIRE a spurious finding; an Inf observed yields
    # z=Inf that serializes to invalid JSON. Both must abstain (fail-closed).
    assert _evaluate(_detector(), bad) is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_history_abstains(bad: float) -> None:
    # A single corrupt baseline sample poisons mean/std -> abstain instead of
    # judging on garbage telemetry.
    poisoned = [8.0, 9.0, bad, 11.0, 12.0]
    assert _evaluate(_detector(), 100.0, values=poisoned) is None


@pytest.mark.parametrize(
    ("z_target", "expected"),
    [
        (3.5, Severity.MEDIUM),
        (4.5, Severity.HIGH),
        (5.5, Severity.CRITICAL),
    ],
)
def test_severity_scales_with_magnitude(z_target: float, expected: Severity) -> None:
    finding = _evaluate(_detector(), 10.0 + z_target * _STD)
    assert finding is not None
    assert finding.severity is expected


def test_idempotency_key_is_deterministic() -> None:
    detector = _detector()
    a = _evaluate(detector, 10.0 + 4.0 * _STD)
    b = _evaluate(detector, 10.0 + 4.5 * _STD)
    assert a is not None and b is not None
    # Same metric + window bucket -> identical dedup key regardless of value.
    assert a.idempotency_key == b.idempotency_key


def test_category_is_configurable() -> None:
    finding = _evaluate(_detector(category=Category.COST), 10.0 + 4.0 * _STD)
    assert finding is not None
    assert finding.category is Category.COST


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"detector_id": ""}, "detector_id"),
        ({"min_samples": 1}, "min_samples"),
        ({"z_threshold": 0.0}, "z_threshold"),
    ],
)
def test_constructor_validates(kwargs: dict[str, object], match: str) -> None:
    base: dict[str, object] = {"detector_id": "d1", "min_samples": 5, "z_threshold": 3.0}
    base.update(kwargs)
    with pytest.raises(ValueError, match=match):
        MetricAnomalyDetector(**base)  # type: ignore[arg-type]


def test_to_event_defaults_to_shadow_and_carries_context() -> None:
    detector = _detector()
    finding = _evaluate(detector, 10.0 + 4.0 * _STD)
    assert finding is not None
    event = detector.to_event(finding)
    assert event.event_type == "anomaly.finding"
    assert event.mode is Mode.SHADOW
    assert event.idempotency_key == finding.idempotency_key
    assert event.resource_ref == "resource:example/rg/vm-a"
    assert event.payload["direction"] == "over"
    assert event.payload["category"] == Category.RELIABILITY.value


def test_to_event_mode_override() -> None:
    detector = _detector()
    finding = _evaluate(detector, 10.0 + 4.0 * _STD)
    assert finding is not None
    event = detector.to_event(finding, mode=Mode.ENFORCE)
    assert event.mode is Mode.ENFORCE


def test_finding_event_re_enters_event_ingest() -> None:
    """The core property: a finding is an ordinary Event that survives
    event-ingest (normalize + dedupe), not a side channel."""
    detector = _detector()
    finding = _evaluate(detector, 10.0 + 4.0 * _STD)
    assert finding is not None
    validator = JsonSchemaEventValidator(
        JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    )
    ingest = EventIngest(validator=validator)

    event = detector.to_event(finding)
    ingested = ingest.ingest(event)
    assert ingested is not None
    assert ingested.event_type == "anomaly.finding"
    # Re-delivery of the same finding dedupes on the stable idempotency key.
    assert ingest.ingest(detector.to_event(finding)) is None
