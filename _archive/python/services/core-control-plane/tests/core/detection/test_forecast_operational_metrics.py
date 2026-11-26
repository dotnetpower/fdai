from __future__ import annotations

import math

import pytest
from fdai.core.detection.forecast_operational_metrics import (
    reduce_forecast_operational_metrics,
)


def test_reducer_reports_accuracy_coverage_lead_time_and_abstention() -> None:
    metrics = reduce_forecast_operational_metrics(
        episode_count=20,
        abstained_count=4,
        outcome_counts={
            "true_positive": 6,
            "magnitude_error": 2,
            "false_positive": 1,
            "false_negative": 2,
            "late_breach": 1,
            "intervention_censored": 1,
            "unscorable": 1,
        },
        mean_lead_time_seconds=900.0,
        median_lead_time_seconds=840.0,
        lead_time_sample_count=8,
    )

    assert metrics.precision == 0.8
    assert metrics.recall == 0.8
    assert metrics.missed_breach_rate == 0.2
    assert metrics.interval_coverage == 0.75
    assert metrics.abstention_rate == 0.2
    assert metrics.scorable_outcome_count == 12
    assert metrics.non_positive_lead_time_count == 0
    assert metrics.execution_authority is False


def test_reducer_keeps_rates_unknown_without_a_denominator() -> None:
    metrics = reduce_forecast_operational_metrics(
        episode_count=0,
        abstained_count=0,
        outcome_counts={},
        mean_lead_time_seconds=None,
        median_lead_time_seconds=None,
        lead_time_sample_count=0,
    )

    assert metrics.precision is None
    assert metrics.recall is None
    assert metrics.missed_breach_rate is None
    assert metrics.interval_coverage is None
    assert metrics.abstention_rate is None


def test_reducer_counts_non_positive_lead_time_without_failing_the_snapshot() -> None:
    metrics = reduce_forecast_operational_metrics(
        episode_count=1,
        abstained_count=0,
        outcome_counts={"true_positive": 1},
        mean_lead_time_seconds=None,
        median_lead_time_seconds=None,
        lead_time_sample_count=0,
        non_positive_lead_time_count=1,
    )

    assert metrics.lead_time_sample_count == 0
    assert metrics.non_positive_lead_time_count == 1


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"episode_count": -1}, "episode_count"),
        ({"abstained_count": 2}, "abstained_count"),
        ({"outcome_counts": {"invented": 1}}, "unsupported label"),
        ({"mean_lead_time_seconds": math.nan}, "mean_lead_time_seconds"),
        ({"lead_time_sample_count": 1}, "sample count"),
        (
            {
                "outcome_counts": {"true_positive": 1},
                "mean_lead_time_seconds": 10.0,
                "median_lead_time_seconds": 10.0,
                "lead_time_sample_count": 2,
            },
            "non-positive",
        ),
    ),
)
def test_reducer_rejects_malformed_or_inconsistent_evidence(
    overrides: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "episode_count": 1,
        "abstained_count": 0,
        "outcome_counts": {},
        "mean_lead_time_seconds": None,
        "median_lead_time_seconds": None,
        "lead_time_sample_count": 0,
    }
    values.update(overrides)

    with pytest.raises(ValueError, match=message):
        reduce_forecast_operational_metrics(**values)  # type: ignore[arg-type]
