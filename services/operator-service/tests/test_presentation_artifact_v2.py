"""Focused v2 presentation compiler and v1 replay compatibility tests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import pytest
from fdai_operator_service.families.conversation.presentation_artifact_v2 import (
    compile_presentation_artifact_v2,
)
from fdai_operator_service.families.conversation.semantic_turn_presentation import (
    semantic_presentation_artifact,
)

_REF = "ontology-function:verified-output"
_SEMANTIC = {
    "disposition": "answered",
    "checks_completed": 1,
    "checks_total": 1,
    "evidence_refs": [_REF],
}


def _details(
    rows: list[Mapping[str, object]],
    *,
    operation: str = "select",
    output_shape: str = "aggregation_table",
    total: int | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "semantic_query_outputs",
        "presentation_context": {
            "operation": operation,
            "output_shape": output_shape,
        },
        "outputs": [
            {
                "node_id": "result",
                "rows": [
                    {"row_id": f"row-{index}", "values": dict(row)}
                    for index, row in enumerate(rows)
                ],
                "returned_rows": len(rows),
                "total_rows": len(rows) if total is None else total,
            }
        ],
    }


@pytest.mark.parametrize(
    ("details", "slot", "kind"),
    (
        (
            _details([{"available": "yes", "count": 4}]),
            "overview",
            "summary",
        ),
        (
            _details([{"observed": 8, "threshold": 10, "status": "within", "unit": "seconds"}]),
            "metrics",
            "threshold_table",
        ),
        (
            _details(
                [
                    {"category": "A", "value": 3, "unit": "requests"},
                    {"category": "B", "value": 5, "unit": "requests"},
                ]
            ),
            "distribution",
            "bar",
        ),
        (
            _details([{"category": "Observed", "numerator": 8, "denominator": 10}]),
            "coverage",
            "coverage",
        ),
        (
            _details(
                [
                    {
                        "timestamp": f"2026-08-19T00:0{index}:00Z",
                        "metric": "requests",
                        "value": index + 1,
                        "unit": "count",
                    }
                    for index in range(3)
                ],
                operation="compare",
                output_shape="temporal_comparison",
            ),
            "trend",
            "time_series",
        ),
        (
            _details(
                [{"metric": "latency", "baseline": 4, "current": 6, "unit": "seconds"}],
                operation="compare",
                output_shape="temporal_comparison",
            ),
            "comparison",
            "comparison",
        ),
        (
            _details(
                [
                    {"timestamp": "2026-08-19T00:00:00Z", "event": "accepted"},
                    {"timestamp": "2026-08-19T00:01:00Z", "event": "verified"},
                ],
                output_shape="topology_graph",
            ),
            "timeline",
            "timeline",
        ),
    ),
)
def test_v2_compiler_selects_from_typed_context_and_shape(
    details: dict[str, object],
    slot: str,
    kind: str,
) -> None:
    artifact = compile_presentation_artifact_v2(
        semantic=_SEMANTIC,
        technical_details=details,
        locale="en",
    )

    assert artifact is not None
    assert artifact["schema_version"] == 2
    block = cast(list[dict[str, object]], artifact["blocks"])[0]
    assert (block["slot_id"], block["kind"]) == (slot, kind)
    if kind in {"bar", "coverage", "time_series", "comparison", "timeline"}:
        data = cast(dict[str, object], block["data"])
        assert isinstance(data["description"], str)
        assert data["exact_table"]


def test_unit_mismatch_and_missing_values_fall_back_without_coercion() -> None:
    details = _details(
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
                "value": None,
                "unit": "percent",
            },
            {
                "timestamp": "2026-08-19T00:02:00Z",
                "metric": "requests",
                "value": 3,
                "unit": "count",
            },
        ],
        operation="compare",
        output_shape="temporal_comparison",
    )

    artifact = compile_presentation_artifact_v2(
        semantic=_SEMANTIC,
        technical_details=details,
        locale="en",
    )

    assert artifact is not None
    blocks = cast(list[dict[str, object]], artifact["blocks"])
    assert blocks[0]["kind"] == "list"
    assert cast(dict[str, object], blocks[0]["data"])["rows"][1]["c2"] == "-"  # type: ignore[index]
    assert blocks[1]["slot_id"] == "limitations"


def test_v2_resource_table_lifts_readable_fields_from_nested_property_bags() -> None:
    details = _details(
        [
            {
                "id": "scope-1/resource-group/rg-fdai",
                "object_type": "Resource",
                "properties": {
                    "id": "scope-1/resource-group/rg-fdai",
                    "name": "rg-fdai",
                    "type": "resource-group",
                    "properties": {
                        "location": "example-region",
                        "tags": {"workload": "fdai"},
                    },
                },
            }
        ],
        output_shape="property_filtered_resources",
    )

    artifact = compile_presentation_artifact_v2(
        semantic=_SEMANTIC,
        technical_details=details,
        locale="en",
    )

    assert artifact is not None
    block = cast(list[dict[str, object]], artifact["blocks"])[0]
    data = cast(dict[str, object], block["data"])
    assert data["columns"] == [
        {"key": "c0", "label": "name"},
        {"key": "c1", "label": "type"},
        {"key": "c2", "label": "location"},
        {"key": "c3", "label": "id"},
        {"key": "c4", "label": "object_type"},
    ]
    assert data["rows"] == [
        {
            "c0": "rg-fdai",
            "c1": "resource-group",
            "c2": "example-region",
            "c3": "scope-1/resource-group/rg-fdai",
            "c4": "Resource",
        }
    ]


def test_unknown_typed_context_fails_closed_instead_of_using_v1_heuristics() -> None:
    details = _details([{"available": "yes", "count": 4}])
    cast(dict[str, str], details["presentation_context"])["output_shape"] = "unknown_shape"

    assert (
        semantic_presentation_artifact(
            semantic=_SEMANTIC,
            technical_details=details,
            locale="en",
        )
        is None
    )


def test_legacy_projection_without_context_stays_v1() -> None:
    details = _details([{"name": "one"}, {"name": "two"}], output_shape="resource_list")
    details.pop("presentation_context")

    artifact = semantic_presentation_artifact(
        semantic={"evidence_refs": [_REF]},
        technical_details=details,
        locale="en",
    )

    assert artifact is not None
    assert artifact["schema_version"] == 1
