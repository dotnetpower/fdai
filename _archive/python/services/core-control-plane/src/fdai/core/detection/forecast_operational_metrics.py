"""Reduce closed forecast episodes into deployment accuracy evidence."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from fdai.shared.contracts.models import ForecastOutcomeLabel

_LABELS = frozenset(item.value for item in ForecastOutcomeLabel)


@dataclass(frozen=True, slots=True)
class ForecastOperationalMetrics:
    """Bounded deployment metrics that never grant promotion authority."""

    episode_count: int
    abstained_count: int
    scorable_outcome_count: int
    precision: float | None
    recall: float | None
    missed_breach_rate: float | None
    interval_coverage: float | None
    abstention_rate: float | None
    mean_lead_time_seconds: float | None
    median_lead_time_seconds: float | None
    lead_time_sample_count: int
    non_positive_lead_time_count: int
    outcome_counts: tuple[tuple[str, int], ...]
    execution_authority: bool = False

    def to_dict(self) -> dict[str, object]:
        """Return a stable repository-safe evidence projection."""

        return {
            "episode_count": self.episode_count,
            "abstained_count": self.abstained_count,
            "scorable_outcome_count": self.scorable_outcome_count,
            "precision": self.precision,
            "recall": self.recall,
            "missed_breach_rate": self.missed_breach_rate,
            "interval_coverage": self.interval_coverage,
            "abstention_rate": self.abstention_rate,
            "mean_lead_time_seconds": self.mean_lead_time_seconds,
            "median_lead_time_seconds": self.median_lead_time_seconds,
            "lead_time_sample_count": self.lead_time_sample_count,
            "non_positive_lead_time_count": self.non_positive_lead_time_count,
            "outcome_counts": dict(self.outcome_counts),
            "execution_authority": self.execution_authority,
        }


def reduce_forecast_operational_metrics(
    *,
    episode_count: int,
    abstained_count: int,
    outcome_counts: Mapping[str, int],
    mean_lead_time_seconds: float | None,
    median_lead_time_seconds: float | None,
    lead_time_sample_count: int,
    non_positive_lead_time_count: int = 0,
) -> ForecastOperationalMetrics:
    """Compute precision, recall, coverage, lead time, and abstention rates."""

    _count("episode_count", episode_count)
    _count("abstained_count", abstained_count)
    _count("lead_time_sample_count", lead_time_sample_count)
    _count("non_positive_lead_time_count", non_positive_lead_time_count)
    if abstained_count > episode_count:
        raise ValueError("forecast abstained_count MUST NOT exceed episode_count")
    if set(outcome_counts) - _LABELS:
        raise ValueError("forecast outcome counts contain an unsupported label")
    for label, count in outcome_counts.items():
        _count(f"outcome_counts[{label}]", count)
    _finite_optional("mean_lead_time_seconds", mean_lead_time_seconds)
    _finite_optional("median_lead_time_seconds", median_lead_time_seconds)
    if (mean_lead_time_seconds is None) != (median_lead_time_seconds is None):
        raise ValueError("forecast lead-time aggregates MUST be present together")
    if (lead_time_sample_count == 0) != (mean_lead_time_seconds is None):
        raise ValueError("forecast lead-time sample count MUST match its aggregates")

    true_positive = outcome_counts.get(ForecastOutcomeLabel.TRUE_POSITIVE.value, 0)
    magnitude_error = outcome_counts.get(ForecastOutcomeLabel.MAGNITUDE_ERROR.value, 0)
    false_positive = outcome_counts.get(ForecastOutcomeLabel.FALSE_POSITIVE.value, 0)
    false_negative = outcome_counts.get(ForecastOutcomeLabel.FALSE_NEGATIVE.value, 0)
    late_breach = outcome_counts.get(ForecastOutcomeLabel.LATE_BREACH.value, 0)
    detected_breach = true_positive + magnitude_error
    if lead_time_sample_count + non_positive_lead_time_count != detected_breach:
        raise ValueError(
            "forecast lead-time samples and non-positive count MUST match "
            "detected in-horizon breaches"
        )

    precision_denominator = detected_breach + false_positive + late_breach
    recall_denominator = detected_breach + false_negative
    interval_denominator = true_positive + magnitude_error
    scorable = sum(
        outcome_counts.get(label.value, 0)
        for label in (
            ForecastOutcomeLabel.TRUE_POSITIVE,
            ForecastOutcomeLabel.FALSE_POSITIVE,
            ForecastOutcomeLabel.FALSE_NEGATIVE,
            ForecastOutcomeLabel.LATE_BREACH,
            ForecastOutcomeLabel.MAGNITUDE_ERROR,
        )
    )
    return ForecastOperationalMetrics(
        episode_count=episode_count,
        abstained_count=abstained_count,
        scorable_outcome_count=scorable,
        precision=_rate(detected_breach, precision_denominator),
        recall=_rate(detected_breach, recall_denominator),
        missed_breach_rate=_rate(false_negative, recall_denominator),
        interval_coverage=_rate(true_positive, interval_denominator),
        abstention_rate=_rate(abstained_count, episode_count),
        mean_lead_time_seconds=mean_lead_time_seconds,
        median_lead_time_seconds=median_lead_time_seconds,
        lead_time_sample_count=lead_time_sample_count,
        non_positive_lead_time_count=non_positive_lead_time_count,
        outcome_counts=tuple(sorted(outcome_counts.items())),
    )


def _count(label: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"forecast {label} MUST be a non-negative integer")


def _finite_optional(label: str, value: float | None) -> None:
    if value is not None and (not math.isfinite(value) or value < 0):
        raise ValueError(f"forecast {label} MUST be finite and non-negative")


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


__all__ = ["ForecastOperationalMetrics", "reduce_forecast_operational_metrics"]
