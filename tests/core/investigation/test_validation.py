"""Validation + helper edge cases for the investigation module."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.core.investigation import Priority, priority_for
from fdai.core.investigation.analyzer import (
    Aggregation,
    Comparison,
    Threshold,
    ThresholdAnalyzer,
    reduce_values,
)
from fdai.core.investigation.contract import AnalyzerFinding
from fdai.core.investigation.recommendations import (
    build_recommendations,
    summarize_priorities,
)
from fdai.shared.contracts.models import Severity
from fdai.shared.providers.metric import StaticMetricProvider

_T = datetime(2026, 7, 10, tzinfo=UTC)


@pytest.mark.parametrize(
    ("how", "expected"),
    [
        (Aggregation.MAX, 9.0),
        (Aggregation.MIN, 1.0),
        (Aggregation.SUM, 12.0),
        (Aggregation.AVG, 4.0),
        (Aggregation.LAST, 2.0),
    ],
)
def test_reduce_values_all_aggregations(how: Aggregation, expected: float) -> None:
    assert reduce_values([9.0, 1.0, 2.0], how) == expected


def test_reduce_values_empty_is_none() -> None:
    assert reduce_values([], Aggregation.MAX) is None


def test_threshold_analyzer_rejects_empty_kind() -> None:
    with pytest.raises(ValueError, match="resource_kind"):
        ThresholdAnalyzer(
            resource_kind="",
            provider=StaticMetricProvider(()),
            thresholds=(),
        )


def test_analyzer_finding_rejects_empty_resource_ref() -> None:
    with pytest.raises(ValueError, match="resource_ref"):
        AnalyzerFinding(
            resource_ref="",
            resource_kind="k",
            signal="s",
            observation="o",
            severity=Severity.LOW,
            occurred_at=_T,
        )


def test_analyzer_finding_rejects_empty_signal() -> None:
    with pytest.raises(ValueError, match="signal"):
        AnalyzerFinding(
            resource_ref="r",
            resource_kind="k",
            signal="",
            observation="o",
            severity=Severity.LOW,
            occurred_at=_T,
        )


def test_priority_for_mapping() -> None:
    assert priority_for(Severity.CRITICAL) is Priority.P1
    assert priority_for(Severity.HIGH) is Priority.P2
    assert priority_for(Severity.MEDIUM) is Priority.P3
    assert priority_for(Severity.LOW) is Priority.P3


def _finding(signal: str, severity: Severity) -> AnalyzerFinding:
    return AnalyzerFinding(
        resource_ref="r",
        resource_kind="k",
        signal=signal,
        observation=f"{signal} {severity.value}",
        severity=severity,
        occurred_at=_T,
    )


def test_recommendations_dedup_keeps_most_severe() -> None:
    # Same (resource, signal); the more severe finding wins.
    recs = build_recommendations(
        [_finding("cpu", Severity.MEDIUM), _finding("cpu", Severity.CRITICAL)]
    )
    assert len(recs) == 1
    assert recs[0].priority is Priority.P1


def test_recommendations_dedup_ignores_less_severe_duplicate() -> None:
    # Reverse order: the first (critical) stays, the second (low) is ignored.
    recs = build_recommendations(
        [_finding("cpu", Severity.CRITICAL), _finding("cpu", Severity.LOW)]
    )
    assert len(recs) == 1
    assert recs[0].priority is Priority.P1


def test_summarize_priorities_counts() -> None:
    recs = build_recommendations([_finding("a", Severity.CRITICAL), _finding("b", Severity.MEDIUM)])
    counts = summarize_priorities(recs)
    assert counts[Priority.P1] == 1
    assert counts[Priority.P3] == 1


def test_threshold_gte_default_aggregation_is_max() -> None:
    t = Threshold(
        metric="m",
        compare=Comparison.GTE,
        bound=1.0,
        severity=Severity.LOW,
        signal="s",
        observation="o",
    )
    assert t.aggregation is Aggregation.MAX
