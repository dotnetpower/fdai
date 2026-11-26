"""Leakage-safe temporal correlation and predictive-precedence evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

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


def test_claim_identity_normalizes_equivalent_cutoff_offsets() -> None:
    cause = _series("request_rate", tuple(float(value) for value in _VALUES))
    effect = _series("latency", (0.0, *(float(value * 2) for value in _VALUES[:-1])))
    analyzer = TemporalCausalityAnalyzer(
        TemporalCausalityConfig(lag_seconds=(3600,), min_samples=12)
    )
    cutoff = effect.samples[-1].timestamp

    first = analyzer.analyze(
        cause=cause,
        effect=effect,
        feature_cutoff=cutoff,
        evidence_refs=("metric-window:offset",),
    )
    second = analyzer.analyze(
        cause=cause,
        effect=effect,
        feature_cutoff=cutoff.astimezone(timezone(timedelta(hours=9))),
        evidence_refs=("metric-window:offset",),
    )

    assert first is not None and second is not None
    assert first.claim_id == second.claim_id


@pytest.mark.parametrize("period", [23, 24, 25])
def test_insufficient_differenced_samples_return_no_claim(period: int) -> None:
    series = _series("metric", tuple(float(value) for value in _VALUES))
    analyzer = TemporalCausalityAnalyzer(
        TemporalCausalityConfig(lag_seconds=(0,), difference_period=period)
    )
    assert (
        analyzer.analyze(
            cause=series,
            effect=series,
            feature_cutoff=series.samples[-1].timestamp,
            evidence_refs=("evidence:short",),
        )
        is None
    )


def test_claim_identity_binds_samples_configuration_and_evidence() -> None:
    cause = _series("cause", tuple(float(value) for value in _VALUES))
    effect = _series("effect", (0.0, *(float(value) for value in _VALUES[:-1])))
    config = TemporalCausalityConfig(lag_seconds=(3600,), min_samples=12)

    def analyze(source=cause, refs=("evidence:one",), settings=config):
        claim = TemporalCausalityAnalyzer(settings).analyze(
            cause=source,
            effect=effect,
            feature_cutoff=effect.samples[-1].timestamp,
            evidence_refs=refs,
        )
        assert claim is not None
        return claim

    base = analyze()
    changed_samples = replace(
        cause, samples=(*cause.samples[:-1], replace(cause.samples[-1], value=99.0))
    )
    assert base.claim_id != analyze(source=changed_samples).claim_id
    assert base.claim_id != analyze(refs=("evidence:two",)).claim_id
    assert base.claim_id != analyze(settings=replace(config, alpha=0.01)).claim_id


def test_multiple_testing_correction_counts_every_searched_lag() -> None:
    cause = _series("cause", tuple(float(value) for value in _VALUES))
    effect = _series("effect", tuple(float(value) for value in reversed(_VALUES)))
    config = TemporalCausalityConfig(
        lag_seconds=(0,),
        min_samples=12,
        difference_period=0,
        candidate_count=2,
    )
    one = TemporalCausalityAnalyzer(config).analyze(
        cause=cause,
        effect=effect,
        feature_cutoff=effect.samples[-1].timestamp,
        evidence_refs=("evidence:one",),
    )
    many = TemporalCausalityAnalyzer(replace(config, lag_seconds=(0, 1, 2))).analyze(
        cause=cause,
        effect=effect,
        feature_cutoff=effect.samples[-1].timestamp,
        evidence_refs=("evidence:one",),
    )
    assert one is not None and many is not None
    assert many.lag_seconds == one.lag_seconds == 0
    assert many.adjusted_p_value == min(1.0, one.adjusted_p_value * 3)


@pytest.mark.parametrize("values", [(1.0,) * 24, tuple(float(value) for value in _VALUES)])
def test_relaxed_thresholds_cannot_turn_zero_lag_or_constant_series_into_precedence(values):
    series = _series("metric", values)
    claim = TemporalCausalityAnalyzer(
        TemporalCausalityConfig(
            lag_seconds=(0,),
            min_abs_correlation=0.0,
            direction_margin=0.0,
            alpha=1.0,
        )
    ).analyze(
        cause=series,
        effect=series,
        feature_cutoff=series.samples[-1].timestamp,
        evidence_refs=("evidence:degenerate",),
    )
    assert claim is not None
    assert claim.evidence_grade is CausalEvidenceGrade.ASSOCIATION
    assert "temporal_precedence_unproven" in claim.falsifiers


def test_temporal_causality_rejects_bool_bounds_and_canonicalizes_evidence_refs() -> None:
    cause = _series("cause", tuple(float(value) for value in _VALUES))
    effect = _series("effect", (0.0, *(float(value) for value in _VALUES[:-1])))
    analyzer = TemporalCausalityAnalyzer(
        TemporalCausalityConfig(lag_seconds=(3600,), min_samples=12)
    )
    claim = analyzer.analyze(
        cause=cause,
        effect=effect,
        feature_cutoff=effect.samples[-1].timestamp,
        evidence_refs=("ref:b", "ref:a", "ref:b"),
    )
    assert claim is not None
    assert claim.evidence_refs == ("ref:a", "ref:b")

    with pytest.raises(ValueError, match="lags MUST be non-empty"):
        TemporalCausalityConfig(lag_seconds=(True,))
    with pytest.raises(ValueError, match="sample and correction bounds"):
        TemporalCausalityConfig(lag_seconds=(0,), min_samples=True)
    with pytest.raises(ValueError, match="min_abs_correlation"):
        TemporalCausalityConfig(lag_seconds=(0,), min_abs_correlation=float("nan"))
