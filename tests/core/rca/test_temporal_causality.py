"""Leakage-safe temporal correlation and predictive-precedence evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.detection.series import MetricSample
from fdai.core.rca import (
    TemporalCausalityAnalyzer,
    TemporalCausalityConfig,
    TemporalSeries,
)
from fdai.shared.contracts.models import CausalEvidenceGrade

_START = datetime(2026, 7, 1, tzinfo=UTC)
_VALUES = (3, 8, 1, 7, 2, 9, 4, 6, 0, 5, 11, 3, 10, 2, 8, 1, 12, 4, 9, 0, 7, 5, 13, 2)


def _series(metric: str, values: tuple[float, ...]) -> TemporalSeries:
    return TemporalSeries(
        metric=metric,
        samples=tuple(
            MetricSample(timestamp=_START + timedelta(hours=index), value=value)
            for index, value in enumerate(values)
        ),
    )


def test_lagged_driver_reaches_predictive_precedence_only() -> None:
    cause = _series("request_rate", tuple(float(value) for value in _VALUES))
    effect_values = (0.0, *(float(value * 2) for value in _VALUES[:-1]))
    effect = _series("latency_p99_ms", effect_values)
    analyzer = TemporalCausalityAnalyzer(
        TemporalCausalityConfig(
            lag_seconds=(0, 3600, 7200),
            min_samples=12,
            min_abs_correlation=0.7,
            direction_margin=0.2,
            candidate_count=3,
        )
    )

    claim = analyzer.analyze(
        cause=cause,
        effect=effect,
        feature_cutoff=effect.samples[-1].timestamp,
        evidence_refs=("metric-window:request-latency",),
    )

    assert claim is not None
    assert claim.lag_seconds == 3600
    assert claim.evidence_grade is CausalEvidenceGrade.PREDICTIVE_PRECEDENCE
    assert claim.adjusted_p_value <= 0.05
    assert claim.falsifiers == ()


def test_common_confounder_does_not_become_predictive_precedence() -> None:
    confounder = _series("traffic", tuple(float(value) for value in _VALUES))
    cause = _series("cpu", tuple(float(value * 2) for value in _VALUES))
    effect = _series("latency", tuple(float(value * 3) for value in _VALUES))
    analyzer = TemporalCausalityAnalyzer(TemporalCausalityConfig(lag_seconds=(0,), min_samples=12))

    claim = analyzer.analyze(
        cause=cause,
        effect=effect,
        confounder=confounder,
        feature_cutoff=effect.samples[-1].timestamp,
        evidence_refs=("metric-window:confounded",),
    )

    assert claim is not None
    assert claim.evidence_grade is CausalEvidenceGrade.ASSOCIATION
    assert "association_below_threshold" in claim.falsifiers
    assert claim.confounder_metric == "traffic"


def test_reverse_direction_ambiguity_blocks_predictive_grade() -> None:
    values = tuple(float(value) for value in _VALUES)
    analyzer = TemporalCausalityAnalyzer(TemporalCausalityConfig(lag_seconds=(0,), min_samples=12))

    claim = analyzer.analyze(
        cause=_series("left", values),
        effect=_series("right", values),
        feature_cutoff=_START + timedelta(hours=len(values) - 1),
        evidence_refs=("metric-window:symmetric",),
    )

    assert claim is not None
    assert claim.evidence_grade is CausalEvidenceGrade.ASSOCIATION
    assert "reverse_direction_not_weaker" in claim.falsifiers


def test_feature_cutoff_rejects_future_sample_leakage() -> None:
    values = tuple(float(value) for value in _VALUES)
    series = _series("metric", values)
    analyzer = TemporalCausalityAnalyzer(TemporalCausalityConfig(lag_seconds=(0,), min_samples=12))

    with pytest.raises(ValueError, match="MUST NOT cross feature_cutoff"):
        analyzer.analyze(
            cause=series,
            effect=series,
            feature_cutoff=series.samples[-2].timestamp,
            evidence_refs=("metric-window:future",),
        )
