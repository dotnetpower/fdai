"""Leakage-safe lagged correlation evidence for bounded RCA hypotheses."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import fmean
from uuid import NAMESPACE_URL, uuid5

from fdai.core.detection.series import MetricSample
from fdai.shared.contracts.models import CausalEvidenceGrade


@dataclass(frozen=True, slots=True)
class TemporalSeries:
    metric: str
    samples: tuple[MetricSample, ...]

    def __post_init__(self) -> None:
        if not self.metric or len(self.samples) < 2:
            raise ValueError("temporal series requires a metric and at least two samples")
        timestamps = tuple(sample.timestamp for sample in self.samples)
        if any(timestamp.tzinfo is None for timestamp in timestamps):
            raise ValueError("temporal series timestamps MUST be timezone-aware")
        if timestamps != tuple(sorted(timestamps)) or len(set(timestamps)) != len(timestamps):
            raise ValueError("temporal series timestamps MUST be unique and ordered")
        if any(not math.isfinite(sample.value) for sample in self.samples):
            raise ValueError("temporal series values MUST be finite")


@dataclass(frozen=True, slots=True)
class TemporalCausalityConfig:
    lag_seconds: tuple[int, ...]
    min_samples: int = 12
    min_abs_correlation: float = 0.5
    alpha: float = 0.05
    direction_margin: float = 0.1
    difference_period: int = 1
    candidate_count: int = 1

    def __post_init__(self) -> None:
        if not self.lag_seconds or any(lag < 0 for lag in self.lag_seconds):
            raise ValueError("temporal causality lags MUST be non-empty and non-negative")
        if len(set(self.lag_seconds)) != len(self.lag_seconds):
            raise ValueError("temporal causality lags MUST be unique")
        if self.min_samples < 4 or self.difference_period < 0 or self.candidate_count < 1:
            raise ValueError("temporal causality sample and correction bounds are invalid")
        if not 0.0 <= self.min_abs_correlation <= 1.0:
            raise ValueError("min_abs_correlation MUST be in [0, 1]")
        if not 0.0 < self.alpha <= 1.0 or not 0.0 <= self.direction_margin <= 1.0:
            raise ValueError("temporal causality alpha and direction margin are invalid")


@dataclass(frozen=True, slots=True)
class TemporalCausalClaim:
    claim_id: str
    cause_metric: str
    effect_metric: str
    lag_seconds: int
    sample_count: int
    correlation: float
    reverse_correlation: float
    adjusted_p_value: float
    evidence_grade: CausalEvidenceGrade
    feature_cutoff: datetime
    confounder_metric: str | None
    evidence_refs: tuple[str, ...]
    falsifiers: tuple[str, ...]


class TemporalCausalityAnalyzer:
    """Rank lagged associations without claiming experimental causality."""

    def __init__(self, config: TemporalCausalityConfig) -> None:
        self._config = config

    def analyze(
        self,
        *,
        cause: TemporalSeries,
        effect: TemporalSeries,
        feature_cutoff: datetime,
        evidence_refs: tuple[str, ...],
        confounder: TemporalSeries | None = None,
    ) -> TemporalCausalClaim | None:
        if feature_cutoff.tzinfo is None:
            raise ValueError("temporal causality feature_cutoff MUST be timezone-aware")
        if not evidence_refs or any(not ref for ref in evidence_refs):
            raise ValueError("temporal causality evidence_refs MUST be non-empty")
        for series in (cause, effect, confounder):
            if series is not None and series.samples[-1].timestamp > feature_cutoff:
                raise ValueError("temporal causality series MUST NOT cross feature_cutoff")

        transformed_cause = _difference(cause, self._config.difference_period)
        transformed_effect = _difference(effect, self._config.difference_period)
        transformed_confounder = (
            _difference(confounder, self._config.difference_period)
            if confounder is not None
            else None
        )
        candidates: list[tuple[float, int, int, float, float, float]] = []
        for lag in sorted(self._config.lag_seconds):
            cause_values, effect_values, confounder_values = _aligned_values(
                transformed_cause,
                transformed_effect,
                lag_seconds=lag,
                confounder=transformed_confounder,
            )
            if len(cause_values) < self._config.min_samples:
                continue
            adjusted_cause, adjusted_effect = _adjust_for_confounder(
                cause_values,
                effect_values,
                confounder_values,
            )
            correlation = _pearson(adjusted_cause, adjusted_effect)
            reverse_cause, reverse_effect, reverse_confounder = _aligned_values(
                transformed_effect,
                transformed_cause,
                lag_seconds=lag,
                confounder=transformed_confounder,
            )
            adjusted_reverse_cause, adjusted_reverse_effect = _adjust_for_confounder(
                reverse_cause,
                reverse_effect,
                reverse_confounder,
            )
            reverse = _pearson(adjusted_reverse_cause, adjusted_reverse_effect)
            p_value = min(
                1.0,
                _correlation_p_value(correlation, len(adjusted_cause))
                * self._config.candidate_count,
            )
            candidates.append(
                (abs(correlation), -lag, len(adjusted_cause), correlation, reverse, p_value)
            )
        if not candidates:
            return None
        _, negative_lag, sample_count, correlation, reverse, adjusted_p = max(candidates)
        lag = -negative_lag
        falsifiers: list[str] = []
        if abs(correlation) < self._config.min_abs_correlation:
            falsifiers.append("association_below_threshold")
        if adjusted_p > self._config.alpha:
            falsifiers.append("multiple_testing_not_significant")
        if abs(correlation) - abs(reverse) < self._config.direction_margin:
            falsifiers.append("reverse_direction_not_weaker")
        grade = (
            CausalEvidenceGrade.PREDICTIVE_PRECEDENCE
            if not falsifiers
            else CausalEvidenceGrade.ASSOCIATION
        )
        identity = (
            f"{cause.metric}:{effect.metric}:{lag}:"
            f"{feature_cutoff.astimezone(UTC).isoformat()}:"
            f"{confounder.metric if confounder is not None else 'none'}"
        )
        return TemporalCausalClaim(
            claim_id=str(uuid5(NAMESPACE_URL, f"fdai-temporal-causal-claim:{identity}")),
            cause_metric=cause.metric,
            effect_metric=effect.metric,
            lag_seconds=lag,
            sample_count=sample_count,
            correlation=correlation,
            reverse_correlation=reverse,
            adjusted_p_value=adjusted_p,
            evidence_grade=grade,
            feature_cutoff=feature_cutoff,
            confounder_metric=confounder.metric if confounder is not None else None,
            evidence_refs=evidence_refs,
            falsifiers=tuple(falsifiers),
        )


def _difference(series: TemporalSeries, period: int) -> TemporalSeries:
    if period == 0:
        return series
    if len(series.samples) <= period:
        return TemporalSeries(metric=series.metric, samples=series.samples)
    samples = tuple(
        MetricSample(
            timestamp=series.samples[index].timestamp,
            value=series.samples[index].value - series.samples[index - period].value,
        )
        for index in range(period, len(series.samples))
    )
    return TemporalSeries(metric=series.metric, samples=samples)


def _aligned_values(
    cause: TemporalSeries,
    effect: TemporalSeries,
    *,
    lag_seconds: int,
    confounder: TemporalSeries | None,
) -> tuple[list[float], list[float], list[float] | None]:
    cause_by_time = {sample.timestamp: sample.value for sample in cause.samples}
    confounder_by_time = (
        {sample.timestamp: sample.value for sample in confounder.samples}
        if confounder is not None
        else None
    )
    cause_values: list[float] = []
    effect_values: list[float] = []
    confounder_values: list[float] = []
    lag = timedelta(seconds=lag_seconds)
    for sample in effect.samples:
        cause_value = cause_by_time.get(sample.timestamp - lag)
        if cause_value is None:
            continue
        if confounder_by_time is not None:
            confounder_value = confounder_by_time.get(sample.timestamp)
            if confounder_value is None:
                continue
            confounder_values.append(confounder_value)
        cause_values.append(cause_value)
        effect_values.append(sample.value)
    return (
        cause_values,
        effect_values,
        confounder_values if confounder is not None else None,
    )


def _adjust_for_confounder(
    cause: list[float],
    effect: list[float],
    confounder: list[float] | None,
) -> tuple[list[float], list[float]]:
    if confounder is None or not confounder:
        return cause, effect
    return _residuals(cause, confounder), _residuals(effect, confounder)


def _residuals(values: list[float], predictor: list[float]) -> list[float]:
    mean_x = fmean(predictor)
    mean_y = fmean(values)
    variance = sum((value - mean_x) ** 2 for value in predictor)
    if variance == 0.0:
        return [value - mean_y for value in values]
    slope = (
        sum(
            (x_value - mean_x) * (y_value - mean_y)
            for x_value, y_value in zip(predictor, values, strict=True)
        )
        / variance
    )
    intercept = mean_y - slope * mean_x
    return [
        y_value - (slope * x_value + intercept)
        for x_value, y_value in zip(predictor, values, strict=True)
    ]


def _pearson(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    mean_left = fmean(left)
    mean_right = fmean(right)
    centered_left = [value - mean_left for value in left]
    centered_right = [value - mean_right for value in right]
    denominator = math.sqrt(
        sum(value * value for value in centered_left)
        * sum(value * value for value in centered_right)
    )
    if denominator == 0.0:
        return 0.0
    return max(
        -1.0,
        min(
            1.0,
            sum(
                left_value * right_value
                for left_value, right_value in zip(centered_left, centered_right, strict=True)
            )
            / denominator,
        ),
    )


def _correlation_p_value(correlation: float, sample_count: int) -> float:
    if sample_count <= 3:
        return 1.0
    clipped = max(-0.999999999, min(0.999999999, correlation))
    z_score = abs(math.atanh(clipped)) * math.sqrt(sample_count - 3)
    return math.erfc(z_score / math.sqrt(2.0))


__all__ = [
    "TemporalCausalClaim",
    "TemporalCausalityAnalyzer",
    "TemporalCausalityConfig",
    "TemporalSeries",
]
