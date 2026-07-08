"""Composite (multivariate) anomaly detector - #7 compound-degradation fusion.

Verifies the fuser abstains below quorum (single-signal noise
suppression), escalates severity with concurrent signals, dedupes
duplicate metrics, and normalizes to a shadow-mode composite event.
"""

from __future__ import annotations

from fdai.core.detection import (
    AnomalyFinding,
    CompositeAnomalyDetector,
    CompositeAnomalyFinding,
)
from fdai.shared.contracts.models import Category, Mode, Severity


def _finding(
    metric: str,
    *,
    resource_ref: str = "res-a",
    z_score: float | None = 3.5,
    direction: str = "over",
    severity: Severity = Severity.MEDIUM,
) -> AnomalyFinding:
    return AnomalyFinding(
        detector_id=f"det-{metric}",
        metric=metric,
        resource_ref=resource_ref,
        window_bucket="2026-07-07T12",
        baseline_mean=50.0,
        baseline_std=5.0,
        observed=70.0,
        z_score=z_score,
        direction=direction,
        category=Category.RELIABILITY,
        severity=severity,
        idempotency_key=f"key-{metric}",
        reason="test",
    )


# ---------------------------------------------------------------------------
# Quorum
# ---------------------------------------------------------------------------


def test_single_signal_below_quorum_abstains() -> None:
    det = CompositeAnomalyDetector(detector_id="comp-1", quorum=2)
    result = det.fuse(
        resource_ref="res-a",
        window_bucket="2026-07-07T12",
        findings=[_finding("latency")],
    )
    assert result is None


def test_quorum_met_yields_composite() -> None:
    det = CompositeAnomalyDetector(detector_id="comp-1", quorum=2)
    result = det.fuse(
        resource_ref="res-a",
        window_bucket="2026-07-07T12",
        findings=[_finding("latency"), _finding("error_rate")],
    )
    assert isinstance(result, CompositeAnomalyFinding)
    assert result.member_count == 2
    assert result.member_metrics == ("error_rate", "latency")  # sorted
    assert result.dominant_direction == "over"


def test_only_matching_resource_members_count() -> None:
    det = CompositeAnomalyDetector(detector_id="comp-1", quorum=2)
    result = det.fuse(
        resource_ref="res-a",
        window_bucket="2026-07-07T12",
        findings=[_finding("latency"), _finding("cpu", resource_ref="res-b")],
    )
    # Only one member is on res-a -> below quorum.
    assert result is None


# ---------------------------------------------------------------------------
# Dedupe + direction
# ---------------------------------------------------------------------------


def test_duplicate_metric_collapses_to_strongest() -> None:
    det = CompositeAnomalyDetector(detector_id="comp-1", quorum=2)
    result = det.fuse(
        resource_ref="res-a",
        window_bucket="2026-07-07T12",
        findings=[
            _finding("latency", z_score=3.0),
            _finding("latency", z_score=6.0),  # same metric, stronger
            _finding("error_rate", z_score=3.5),
        ],
    )
    assert result is not None
    # Two distinct metrics only; the duplicate did not inflate the quorum.
    assert result.member_count == 2
    assert set(result.member_metrics) == {"latency", "error_rate"}


def test_mixed_directions_report_mixed() -> None:
    det = CompositeAnomalyDetector(detector_id="comp-1", quorum=2)
    result = det.fuse(
        resource_ref="res-a",
        window_bucket="2026-07-07T12",
        findings=[
            _finding("latency", direction="over"),
            _finding("throughput", direction="under"),
        ],
    )
    assert result is not None
    assert result.dominant_direction == "mixed"


# ---------------------------------------------------------------------------
# Severity escalation
# ---------------------------------------------------------------------------


def test_three_concurrent_signals_escalate_to_critical() -> None:
    det = CompositeAnomalyDetector(detector_id="comp-1", quorum=2)
    result = det.fuse(
        resource_ref="res-a",
        window_bucket="2026-07-07T12",
        findings=[_finding("latency"), _finding("error_rate"), _finding("cpu")],
    )
    assert result is not None
    assert result.severity is Severity.CRITICAL


def test_combined_magnitude_is_root_sum_square() -> None:
    det = CompositeAnomalyDetector(detector_id="comp-1", quorum=2)
    result = det.fuse(
        resource_ref="res-a",
        window_bucket="2026-07-07T12",
        findings=[_finding("a", z_score=3.0), _finding("b", z_score=4.0)],
    )
    assert result is not None
    # sqrt(3^2 + 4^2) = 5.0
    assert result.combined_magnitude == 5.0


def test_flat_baseline_member_contributes_fixed_weight() -> None:
    det = CompositeAnomalyDetector(detector_id="comp-1", quorum=2)
    result = det.fuse(
        resource_ref="res-a",
        window_bucket="2026-07-07T12",
        findings=[_finding("a", z_score=None), _finding("b", z_score=None)],
    )
    assert result is not None
    # sqrt(5^2 + 5^2) ~= 7.07
    assert 7.0 < result.combined_magnitude < 7.1


# ---------------------------------------------------------------------------
# Event normalization + determinism
# ---------------------------------------------------------------------------


def test_to_event_is_shadow_mode_composite() -> None:
    det = CompositeAnomalyDetector(detector_id="comp-1", quorum=2)
    result = det.fuse(
        resource_ref="res-a",
        window_bucket="2026-07-07T12",
        findings=[_finding("latency"), _finding("error_rate")],
    )
    assert result is not None
    event = det.to_event(result)
    assert event.mode is Mode.SHADOW
    assert event.event_type == "anomaly.composite"
    assert event.resource_ref == "res-a"
    assert event.idempotency_key == result.idempotency_key


def test_fusion_is_deterministic_regardless_of_input_order() -> None:
    det = CompositeAnomalyDetector(detector_id="comp-1", quorum=2)
    findings = [_finding("latency"), _finding("error_rate"), _finding("cpu")]
    first = det.fuse(resource_ref="res-a", window_bucket="2026-07-07T12", findings=findings)
    second = det.fuse(
        resource_ref="res-a",
        window_bucket="2026-07-07T12",
        findings=list(reversed(findings)),
    )
    assert first is not None
    assert second is not None
    assert first.idempotency_key == second.idempotency_key
    assert first.combined_magnitude == second.combined_magnitude
    assert first.member_metrics == second.member_metrics


def test_quorum_below_two_is_rejected() -> None:
    import pytest

    with pytest.raises(ValueError, match="quorum MUST be >= 2"):
        CompositeAnomalyDetector(detector_id="comp-1", quorum=1)


def test_non_finite_z_member_is_excluded_from_quorum() -> None:
    """A NaN / inf z-score member is corrupt and must not fill the quorum."""
    det = CompositeAnomalyDetector(detector_id="comp-1", quorum=2)
    result = det.fuse(
        resource_ref="res-a",
        window_bucket="2026-07-07T12",
        findings=[_finding("latency"), _finding("error_rate", z_score=float("nan"))],
    )
    # Only one valid member remains -> below quorum -> no composite.
    assert result is None


def test_inf_z_member_does_not_inflate_magnitude() -> None:
    det = CompositeAnomalyDetector(detector_id="comp-1", quorum=2)
    result = det.fuse(
        resource_ref="res-a",
        window_bucket="2026-07-07T12",
        findings=[
            _finding("latency"),
            _finding("error_rate"),
            _finding("cpu", z_score=float("inf")),
        ],
    )
    assert result is not None
    # The corrupt member is dropped; magnitude stays finite.
    import math

    assert math.isfinite(result.combined_magnitude)
    assert "cpu" not in result.member_metrics
