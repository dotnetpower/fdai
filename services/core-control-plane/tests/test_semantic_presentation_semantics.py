"""Deterministic presentation-semantics projection tests."""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from fdai_core_service.semantic_presentation_semantics import project_presentation_semantics


def _outputs(rows: list[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "node_id": "result",
            "rows": [
                {"row_id": f"row-{index}", "values": dict(row)} for index, row in enumerate(rows)
            ],
        }
    ]


@pytest.mark.parametrize(
    ("operation", "output_shape", "rows", "expected"),
    (
        (
            "select",
            "target_resource_metric_series",
            [
                {
                    "timestamp": "2026-08-22T00:00:00Z",
                    "metric": "requests",
                    "unit": "count",
                    "value": 1,
                },
                {
                    "timestamp": "2026-08-22T00:01:00Z",
                    "metric": "requests",
                    "unit": "count",
                    "value": 2,
                },
                {
                    "timestamp": "2026-08-22T00:02:00Z",
                    "metric": "requests",
                    "unit": "count",
                    "value": 3,
                },
            ],
            {"shape": "temporal_series", "fields": {}},
        ),
        (
            "select",
            "target_resource_metric_series",
            [
                {
                    "timestamp": "2026-08-22T00:00:00Z",
                    "metric": "cost",
                    "unit": "usd",
                    "cumulative_value": 1,
                },
                {
                    "timestamp": "2026-08-22T00:01:00Z",
                    "metric": "cost",
                    "unit": "usd",
                    "cumulative_value": 3,
                },
                {
                    "timestamp": "2026-08-22T00:02:00Z",
                    "metric": "cost",
                    "unit": "usd",
                    "cumulative_value": 6,
                },
            ],
            {"shape": "cumulative_series", "fields": {}},
        ),
        (
            "select",
            "aggregation_table",
            [
                {"category": "A", "value": 3, "unit": "count"},
                {"category": "B", "value": 5, "unit": "count"},
            ],
            {"shape": "categorical_comparison", "fields": {}},
        ),
        (
            "select",
            "aggregation_table",
            [
                {"rank": 1, "category": "A", "value": 5, "unit": "count"},
                {"rank": 2, "category": "B", "value": 3, "unit": "count"},
            ],
            {"shape": "ranking", "fields": {}},
        ),
        (
            "select",
            "aggregation_table",
            [
                {"category": "A", "value": 3, "total": 10, "unit": "count"},
                {"category": "B", "value": 7, "total": 10, "unit": "count"},
            ],
            {"shape": "part_to_whole", "fields": {}},
        ),
        (
            "select",
            "aggregation_table",
            [{"category": "Observed", "numerator": 8, "denominator": 10}],
            {"shape": "coverage", "fields": {}},
        ),
        (
            "compare",
            "temporal_comparison",
            [{"baseline": 4, "current": 6, "target": 8, "unit": "seconds"}],
            {"shape": "role_comparison", "fields": {}},
        ),
        (
            "select",
            "resource_event_history",
            [
                {"timestamp": "2026-08-22T00:00:00Z", "event": "started"},
                {"timestamp": "2026-08-22T00:01:00Z", "event": "completed"},
            ],
            {"shape": "chronology", "fields": {}},
        ),
        (
            "compare",
            "aggregation_table",
            [{"label": "A", "x": 1, "y": 2}, {"label": "B", "x": 2, "y": 4}],
            {"shape": "correlation", "fields": {"label": "label", "x": "x", "y": "y"}},
        ),
        (
            "select",
            "aggregation_table",
            [
                {"row": "api", "column": "east", "value": 1},
                {"row": "api", "column": "west", "value": 2},
            ],
            {
                "shape": "categorical_matrix",
                "fields": {"row": "row", "column": "column", "value": "value"},
            },
        ),
    ),
)
def test_projects_ten_proven_semantic_shapes(
    operation: str,
    output_shape: str,
    rows: list[Mapping[str, object]],
    expected: Mapping[str, object],
) -> None:
    assert (
        project_presentation_semantics(
            operation=operation,
            output_shape=output_shape,
            outputs=_outputs(rows),
        )
        == expected
    )


def test_omits_ambiguous_or_incomplete_semantics() -> None:
    assert (
        project_presentation_semantics(
            operation="select",
            output_shape="aggregation_table",
            outputs=_outputs([{"category": "A", "value": 3}]),
        )
        is None
    )
    assert (
        project_presentation_semantics(
            operation="compare",
            output_shape="aggregation_table",
            outputs=_outputs([{"label": "A", "x": 1, "y": None}]),
        )
        is None
    )


def test_explicit_comparison_roles_take_precedence_over_temporal_fields() -> None:
    assert project_presentation_semantics(
        operation="compare",
        output_shape="temporal_comparison",
        outputs=_outputs(
            [
                {
                    "timestamp": "2026-08-22T00:00:00Z",
                    "metric": "latency",
                    "unit": "milliseconds",
                    "value": 6,
                    "baseline": 4,
                    "current": 6,
                    "target": 5,
                }
            ]
        ),
    ) == {"shape": "role_comparison", "fields": {}}


def test_decreasing_cumulative_values_do_not_claim_cumulative_semantics() -> None:
    assert (
        project_presentation_semantics(
            operation="select",
            output_shape="target_resource_metric_series",
            outputs=_outputs(
                [
                    {
                        "timestamp": f"2026-08-22T00:0{index}:00Z",
                        "metric": "cost",
                        "unit": "usd",
                        "cumulative_value": value,
                    }
                    for index, value in enumerate((3, 2, 4))
                ]
            ),
        )
        is None
    )


def test_duplicate_matrix_coordinates_do_not_claim_heatmap_semantics() -> None:
    assert (
        project_presentation_semantics(
            operation="select",
            output_shape="aggregation_table",
            outputs=_outputs(
                [
                    {"row": "api", "column": "east", "value": 1},
                    {"row": "api", "column": "east", "value": 2},
                ]
            ),
        )
        is None
    )


def test_empty_correlation_labels_do_not_claim_scatter_semantics() -> None:
    assert (
        project_presentation_semantics(
            operation="compare",
            output_shape="aggregation_table",
            outputs=_outputs(
                [
                    {"label": "", "x": 1, "y": 2},
                    {"label": "B", "x": 2, "y": 4},
                ]
            ),
        )
        is None
    )


def test_non_rfc3339_timestamps_do_not_claim_temporal_semantics() -> None:
    assert (
        project_presentation_semantics(
            operation="select",
            output_shape="target_resource_metric_series",
            outputs=_outputs(
                [
                    {
                        "timestamp": f"2026-08-22 00:0{index}:00+00:00",
                        "metric": "requests",
                        "unit": "count",
                        "value": value,
                    }
                    for index, value in enumerate((1, 3, 2))
                ]
            ),
        )
        is None
    )
