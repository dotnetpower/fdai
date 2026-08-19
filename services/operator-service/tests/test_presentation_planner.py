"""Decision-matrix tests for deterministic semantic presentation planning."""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from fdai_operator_service.families.conversation.presentation_planner import (
    PresentationIntent,
    PresentationKind,
    analyze_evidence_shape,
    plan_presentation,
)


def _output(
    rows: list[Mapping[str, object]],
    *,
    total: int | None = None,
    limitations: list[str] | None = None,
) -> dict[str, object]:
    return {
        "rows": [{"row_id": f"row-{index}", "values": dict(row)} for index, row in enumerate(rows)],
        "returned_rows": len(rows),
        "total_rows": len(rows) if total is None else total,
        **({"limitations": limitations} if limitations is not None else {}),
    }


def _decision(
    intent: PresentationIntent,
    rows: list[Mapping[str, object]],
    *,
    verified: bool = True,
    total: int | None = None,
    limitations: list[str] | None = None,
) -> tuple[PresentationKind, bool]:
    shape = analyze_evidence_shape(
        _output(rows, total=total, limitations=limitations),
        verified=verified,
    )
    decision = plan_presentation(intent=intent, shape=shape)
    return decision.kind, decision.include_exact_table


@pytest.mark.parametrize(
    ("intent", "rows", "expected", "exact_table"),
    (
        (
            PresentationIntent.SUMMARY,
            [{"availability": "available", "count": 4}],
            PresentationKind.SUMMARY,
            False,
        ),
        (
            PresentationIntent.EXACT,
            [{"resource_id": "opaque-a", "status": "ready"}],
            PresentationKind.TABLE,
            False,
        ),
        (
            PresentationIntent.RECORDS,
            [{"label": "Owner", "value": "Assigned"}],
            PresentationKind.LIST,
            False,
        ),
        (
            PresentationIntent.THRESHOLD,
            [{"observed": 8, "threshold": 10, "status": "within", "unit": "seconds"}],
            PresentationKind.THRESHOLD_TABLE,
            False,
        ),
        (
            PresentationIntent.DISTRIBUTION,
            [
                {"category": "A", "value": 3, "unit": "requests"},
                {"category": "B", "value": 5, "unit": "requests"},
            ],
            PresentationKind.BAR,
            True,
        ),
        (
            PresentationIntent.COVERAGE,
            [{"category": "Observed", "numerator": 8, "denominator": 10}],
            PresentationKind.COVERAGE,
            True,
        ),
        (
            PresentationIntent.TREND,
            [
                {
                    "timestamp": f"2026-08-19T00:0{index}:00Z",
                    "metric": "requests",
                    "value": index,
                    "unit": "count",
                }
                for index in range(3)
            ],
            PresentationKind.TIME_SERIES,
            True,
        ),
        (
            PresentationIntent.COMPARISON,
            [{"baseline": 4, "current": 6, "target": 8, "unit": "seconds"}],
            PresentationKind.COMPARISON,
            True,
        ),
        (
            PresentationIntent.CHRONOLOGY,
            [
                {"timestamp": "2026-08-19T00:00:00Z", "event": "accepted"},
                {"timestamp": "2026-08-19T00:01:00Z", "event": "verified"},
            ],
            PresentationKind.TIMELINE,
            False,
        ),
    ),
)
def test_planner_selects_from_verified_intent_and_shape(
    intent: PresentationIntent,
    rows: list[Mapping[str, object]],
    expected: PresentationKind,
    exact_table: bool,
) -> None:
    assert _decision(intent, rows) == (expected, exact_table)


@pytest.mark.parametrize(
    ("intent", "rows", "expected"),
    (
        (
            PresentationIntent.TREND,
            [
                {
                    "timestamp": "2026-08-19T00:00:00Z",
                    "metric": "requests",
                    "value": 1,
                    "unit": "count",
                },
                {
                    "timestamp": "2026-08-19T00:01:00Z",
                    "metric": "requests",
                    "value": 2,
                    "unit": "percent",
                },
                {
                    "timestamp": "2026-08-19T00:02:00Z",
                    "metric": "requests",
                    "value": 3,
                    "unit": "count",
                },
            ],
            PresentationKind.TABLE,
        ),
        (
            PresentationIntent.TREND,
            [
                {
                    "timestamp": "2026-08-19T00:00:00Z",
                    "metric": "requests",
                    "value": 1,
                    "unit": "count",
                },
                {
                    "timestamp": "2026-08-19T00:01:00Z",
                    "metric": "requests",
                    "value": 2,
                    "unit": "count",
                },
            ],
            PresentationKind.TABLE,
        ),
        (
            PresentationIntent.DISTRIBUTION,
            [{"category": "Only", "value": 3, "unit": "count"}],
            PresentationKind.TABLE,
        ),
        (
            PresentationIntent.COVERAGE,
            [{"category": "Observed", "numerator": 0, "denominator": 0}],
            PresentationKind.TABLE,
        ),
    ),
)
def test_chart_rules_fall_back_without_inventing_values(
    intent: PresentationIntent,
    rows: list[Mapping[str, object]],
    expected: PresentationKind,
) -> None:
    assert _decision(intent, rows)[0] is expected


def test_incomplete_or_unverified_evidence_never_selects_a_chart() -> None:
    rows = [
        {"category": "A", "value": 3, "unit": "count"},
        {"category": "B", "value": 5, "unit": "count"},
    ]

    assert _decision(PresentationIntent.DISTRIBUTION, rows, total=3)[0] is PresentationKind.LIST
    assert (
        _decision(
            PresentationIntent.DISTRIBUTION,
            rows,
            limitations=["partial evidence"],
        )[0]
        is PresentationKind.LIST
    )
    assert _decision(PresentationIntent.DISTRIBUTION, rows, verified=False)[0] is (
        PresentationKind.CALLOUT
    )


def test_missing_value_stays_a_record_fallback_instead_of_zero() -> None:
    rows = [
        {"category": "A", "value": 3, "unit": "count"},
        {"category": "B", "value": None, "unit": "count"},
    ]

    shape = analyze_evidence_shape(_output(rows), verified=True)
    decision = plan_presentation(intent=PresentationIntent.DISTRIBUTION, shape=shape)

    assert shape.missing_values is True
    assert shape.records[1]["value"] is None
    assert decision.kind is PresentationKind.LIST
