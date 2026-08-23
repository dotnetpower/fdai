"""Decision-matrix tests for deterministic semantic presentation planning."""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from fdai_operator_service.families.conversation.presentation_planner import (
    PresentationIntent,
    PresentationKind,
    SemanticShape,
    VisualizationKind,
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


def test_verified_complete_zero_rows_are_not_unavailable() -> None:
    shape = analyze_evidence_shape(_output([]), verified=True)

    decision = plan_presentation(intent=PresentationIntent.COMPARISON, shape=shape)

    assert shape.complete is True
    assert shape.unavailable is False
    assert decision.kind is PresentationKind.CALLOUT
    assert decision.reason_code == "verified_empty_result"


@pytest.mark.parametrize(
    ("semantic_shape", "intent", "rows", "semantic_fields", "kind", "visualization"),
    (
        (
            SemanticShape.TEMPORAL_SERIES,
            PresentationIntent.TREND,
            [
                {
                    "timestamp": f"2026-08-19T00:0{i}:00Z",
                    "metric": "requests",
                    "value": i + 1,
                    "unit": "count",
                }
                for i in range(3)
            ],
            {},
            PresentationKind.TIME_SERIES,
            VisualizationKind.LINE,
        ),
        (
            SemanticShape.CUMULATIVE_SERIES,
            PresentationIntent.TREND,
            [
                {
                    "timestamp": f"2026-08-19T00:0{i}:00Z",
                    "metric": "cost",
                    "value": i + 1,
                    "unit": "usd",
                }
                for i in range(3)
            ],
            {},
            PresentationKind.TIME_SERIES,
            VisualizationKind.AREA,
        ),
        (
            SemanticShape.CATEGORICAL_COMPARISON,
            PresentationIntent.DISTRIBUTION,
            [
                {"category": "A", "value": 3, "unit": "count"},
                {"category": "B", "value": 5, "unit": "count"},
            ],
            {},
            PresentationKind.BAR,
            VisualizationKind.BAR,
        ),
        (
            SemanticShape.RANKING,
            PresentationIntent.DISTRIBUTION,
            [
                {"rank": 1, "category": "A", "value": 5, "unit": "count"},
                {"rank": 2, "category": "B", "value": 3, "unit": "count"},
            ],
            {},
            PresentationKind.BAR,
            VisualizationKind.BAR_LIST,
        ),
        (
            SemanticShape.PART_TO_WHOLE,
            PresentationIntent.DISTRIBUTION,
            [
                {"category": "A", "value": 3, "total": 10, "unit": "count"},
                {"category": "B", "value": 7, "total": 10, "unit": "count"},
            ],
            {},
            PresentationKind.BAR,
            VisualizationKind.DONUT,
        ),
        (
            SemanticShape.COVERAGE,
            PresentationIntent.COVERAGE,
            [{"category": "Observed", "numerator": 8, "denominator": 10}],
            {},
            PresentationKind.COVERAGE,
            VisualizationKind.CATEGORY_BAR,
        ),
        (
            SemanticShape.ROLE_COMPARISON,
            PresentationIntent.COMPARISON,
            [{"baseline": 4, "current": 6, "target": 8, "unit": "seconds"}],
            {},
            PresentationKind.COMPARISON,
            VisualizationKind.COMPARISON_BAR,
        ),
        (
            SemanticShape.CHRONOLOGY,
            PresentationIntent.CHRONOLOGY,
            [
                {"timestamp": "2026-08-19T00:00:00Z", "event": "accepted"},
                {"timestamp": "2026-08-19T00:01:00Z", "event": "verified"},
            ],
            {},
            PresentationKind.TIMELINE,
            VisualizationKind.TRACKER,
        ),
        (
            SemanticShape.CORRELATION,
            PresentationIntent.CORRELATION,
            [
                {"name": "A", "latency": 12, "coverage": 94},
                {"name": "B", "latency": 28, "coverage": 88},
            ],
            {"label": "name", "x": "latency", "y": "coverage"},
            PresentationKind.SCATTER,
            VisualizationKind.SCATTER,
        ),
        (
            SemanticShape.CATEGORICAL_MATRIX,
            PresentationIntent.MATRIX,
            [
                {"day": "Mon", "window": "AM", "count": 3},
                {"day": "Tue", "window": "PM", "count": 5},
            ],
            {"row": "window", "column": "day", "value": "count"},
            PresentationKind.HEATMAP,
            VisualizationKind.HEATMAP,
        ),
    ),
)
def test_planner_selects_ten_ontology_grounded_visualizations(
    semantic_shape: SemanticShape,
    intent: PresentationIntent,
    rows: list[Mapping[str, object]],
    semantic_fields: Mapping[str, str],
    kind: PresentationKind,
    visualization: VisualizationKind,
) -> None:
    shape = analyze_evidence_shape(
        _output(rows),
        verified=True,
        semantic_shape=semantic_shape,
        semantic_fields=semantic_fields,
    )
    decision = plan_presentation(intent=intent, shape=shape)
    assert (decision.kind, decision.visualization) == (kind, visualization)


@pytest.mark.parametrize(
    ("semantic_shape", "rows"),
    (
        (
            SemanticShape.PART_TO_WHOLE,
            [
                {"category": "A", "value": 3, "unit": "count"},
                {"category": "B", "value": 7, "unit": "count"},
            ],
        ),
        (
            SemanticShape.RANKING,
            [
                {"category": "A", "value": 5, "unit": "count"},
                {"category": "B", "value": 3, "unit": "count"},
            ],
        ),
    ),
)
def test_semantic_metadata_cannot_upgrade_a_bar_without_row_level_proof(
    semantic_shape: SemanticShape,
    rows: list[Mapping[str, object]],
) -> None:
    shape = analyze_evidence_shape(
        _output(rows),
        verified=True,
        semantic_shape=semantic_shape,
    )

    decision = plan_presentation(intent=PresentationIntent.DISTRIBUTION, shape=shape)

    assert decision.kind is PresentationKind.BAR
    assert decision.visualization is VisualizationKind.BAR


def test_decreasing_cumulative_metadata_downgrades_to_a_line() -> None:
    shape = analyze_evidence_shape(
        _output(
            [
                {
                    "timestamp": f"2026-08-19T00:0{index}:00Z",
                    "metric": "cost",
                    "value": value,
                    "unit": "usd",
                }
                for index, value in enumerate((3, 2, 4))
            ]
        ),
        verified=True,
        semantic_shape=SemanticShape.CUMULATIVE_SERIES,
    )

    decision = plan_presentation(intent=PresentationIntent.TREND, shape=shape)

    assert decision.kind is PresentationKind.TIME_SERIES
    assert decision.visualization is VisualizationKind.LINE


def test_duplicate_matrix_coordinates_fall_back_to_an_exact_table() -> None:
    shape = analyze_evidence_shape(
        _output(
            [
                {"day": "Mon", "window": "AM", "count": 3},
                {"day": "Mon", "window": "AM", "count": 5},
            ]
        ),
        verified=True,
        semantic_shape=SemanticShape.CATEGORICAL_MATRIX,
        semantic_fields={"row": "window", "column": "day", "value": "count"},
    )

    decision = plan_presentation(intent=PresentationIntent.MATRIX, shape=shape)

    assert decision.kind is PresentationKind.TABLE
    assert decision.visualization is VisualizationKind.NONE


def test_missing_timeline_label_falls_back_to_exact_records() -> None:
    shape = analyze_evidence_shape(
        _output(
            [
                {"timestamp": "2026-08-19T00:00:00Z", "event": "accepted"},
                {"timestamp": "2026-08-19T00:01:00Z", "event": None},
            ]
        ),
        verified=True,
        semantic_shape=SemanticShape.CHRONOLOGY,
    )

    decision = plan_presentation(intent=PresentationIntent.CHRONOLOGY, shape=shape)

    assert decision.kind is PresentationKind.LIST
    assert decision.visualization is VisualizationKind.NONE


def test_empty_scatter_label_falls_back_to_an_exact_table() -> None:
    shape = analyze_evidence_shape(
        _output(
            [
                {"name": "", "latency": 12, "coverage": 94},
                {"name": "B", "latency": 28, "coverage": 88},
            ]
        ),
        verified=True,
        semantic_shape=SemanticShape.CORRELATION,
        semantic_fields={"label": "name", "x": "latency", "y": "coverage"},
    )

    decision = plan_presentation(intent=PresentationIntent.CORRELATION, shape=shape)

    assert decision.kind is PresentationKind.TABLE
    assert decision.visualization is VisualizationKind.NONE


def test_non_rfc3339_timestamps_fall_back_to_an_exact_table() -> None:
    shape = analyze_evidence_shape(
        _output(
            [
                {
                    "timestamp": f"2026-08-19 00:0{index}:00+00:00",
                    "metric": "requests",
                    "value": value,
                    "unit": "count",
                }
                for index, value in enumerate((1, 3, 2))
            ]
        ),
        verified=True,
        semantic_shape=SemanticShape.TEMPORAL_SERIES,
    )

    decision = plan_presentation(intent=PresentationIntent.TREND, shape=shape)

    assert decision.kind is PresentationKind.TABLE
    assert decision.visualization is VisualizationKind.NONE
