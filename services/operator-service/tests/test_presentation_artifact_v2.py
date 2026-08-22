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


def test_target_health_assessment_uses_compact_overview_and_gap_blocks() -> None:
    details = _details(
        [
            {
                "overall_assessment": "insufficient_evidence",
                "evidence_sufficient": False,
                "platform_lifecycle": "observed_running",
                "readiness": "not_proven",
                "application_service_health": "not_proven",
                "stability": "process_stability_not_proven",
                "resource_pressure": "cpu_observed_capacity_unknown",
                "source_observed_at": "2026-08-21T00:09:00Z",
                "inventory_read_at": "2026-08-21T00:10:00Z",
                "metric_window_end": "2026-08-21T00:10:00Z",
                "evidence_gaps": ("process_restart_count_unavailable, runtime_logs_unavailable"),
                "execution_authority": False,
            }
        ],
        operation="validate",
        output_shape="target_health_assessment",
    )

    artifact = compile_presentation_artifact_v2(
        semantic=_SEMANTIC,
        technical_details=details,
        locale="en",
    )

    assert artifact is not None
    blocks = cast(list[dict[str, object]], artifact["blocks"])
    assert [block["slot_id"] for block in blocks] == ["overview", "limitations"]
    assert blocks[0]["title"] == "Health evidence assessment"
    summary = cast(dict[str, object], blocks[0]["data"])
    items = cast(list[dict[str, str]], summary["items"])
    assert items[0] == {
        "label": "Overall",
        "value": "insufficient evidence",
        "tone": "neutral",
    }
    limitations = cast(dict[str, object], blocks[1]["data"])
    lines = cast(list[str], limitations["lines"])
    assert "Source observation: 2026-08-21T00:09:00Z" in lines
    assert "process restart count unavailable" in lines
    assert "runtime logs unavailable" in lines


def test_error_activity_correlation_uses_summary_and_window_blocks() -> None:
    details = _details(
        [
            {
                "error_trend": "increased",
                "baseline_error_total": 1.0,
                "current_error_total": 3.0,
                "baseline_window_start": "2026-08-20T23:10:00Z",
                "baseline_window_end": "2026-08-20T23:40:00Z",
                "current_window_start": "2026-08-20T23:40:00Z",
                "current_window_end": "2026-08-21T00:10:00Z",
                "activity_state": "changes_observed",
                "activity_change_count": 1,
                "correlation_assessment": "cooccurrence_observed_not_causation",
                "causal_claim_supported": False,
                "evidence_gaps": "runtime_logs_unavailable",
                "execution_authority": False,
            }
        ],
        operation="compare",
        output_shape="target_error_activity_correlation",
    )

    artifact = compile_presentation_artifact_v2(
        semantic=_SEMANTIC,
        technical_details=details,
        locale="en",
    )

    assert artifact is not None
    blocks = cast(list[dict[str, object]], artifact["blocks"])
    assert [block["slot_id"] for block in blocks] == ["overview", "limitations"]
    assert blocks[0]["title"] == "Request errors and Activity Log correlation"
    summary = cast(dict[str, object], blocks[0]["data"])
    items = cast(list[dict[str, str]], summary["items"])
    assert items[0] == {
        "label": "Request error trend",
        "value": "increased",
        "tone": "neutral",
    }
    limitations = cast(dict[str, object], blocks[1]["data"])
    lines = cast(list[str], limitations["lines"])
    assert "Current window end: 2026-08-21T00:10:00Z" in lines
    assert "runtime logs unavailable" in lines
    assert "Co-occurrence in the same window does not establish causation." in lines


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


@pytest.mark.parametrize("row_count", (1, 11, 20))
def test_v2_resource_table_keeps_stable_cardinality(row_count: int) -> None:
    details = _details(
        [
            {
                "id": f"resource-{index}",
                "object_type": "Resource",
                "properties": {
                    "name": f"resource-with-a-deliberately-long-readable-name-{index}",
                    "type": "resource-group",
                },
            }
            for index in range(row_count)
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
    assert block["kind"] == "table"
    data = cast(dict[str, object], block["data"])
    assert data["columns"] == [
        {"key": "c0", "label": "name"},
        {"key": "c1", "label": "type"},
    ]
    assert len(cast(list[object], data["rows"])) == row_count


def test_v2_target_candidates_render_as_a_verified_name_type_table() -> None:
    details = _details(
        [
            {"name": "app-api", "type": "compute.container-app"},
            {"name": "app-worker", "type": "compute.container-app"},
        ],
        output_shape="resource_target_candidates",
    )
    outputs = cast(list[dict[str, object]], details["outputs"])
    outputs[0]["source_complete"] = True

    artifact = compile_presentation_artifact_v2(
        semantic=_SEMANTIC,
        technical_details=details,
        locale="ko",
    )

    assert artifact is not None
    blocks = cast(list[dict[str, object]], artifact["blocks"])
    assert [block["slot_id"] for block in blocks] == ["overview", "records"]
    overview = cast(dict[str, object], blocks[0]["data"])
    items = cast(list[dict[str, str]], overview["items"])
    assert items == [
        {"label": "검증된 후보", "value": "2", "tone": "neutral"},
        {"label": "범위 완전성", "value": "complete", "tone": "neutral"},
        {
            "label": "다음 단계",
            "value": "표에서 확인할 리소스의 정확한 이름 또는 리소스 ID를 지정하세요.",
            "tone": "attention",
        },
    ]
    block = blocks[1]
    assert (block["slot_id"], block["kind"]) == ("records", "table")
    data = cast(dict[str, object], block["data"])
    assert data["columns"] == [
        {"key": "c0", "label": "name"},
        {"key": "c1", "label": "type"},
    ]


def test_v2_resource_state_rows_render_as_a_korean_verified_table() -> None:
    details = _details(
        [
            {
                "name": "database-a",
                "type": "postgresql-server",
                "observed_state": "Stopped",
                "state_concept": "resource_state.stopped",
                "source_observed_at": "2026-08-21T11:00:00+00:00",
                "inventory_read_at": "2026-08-21T11:05:00+00:00",
                "execution_authority": False,
            }
        ],
        output_shape="resource_state_list",
    )

    artifact = compile_presentation_artifact_v2(
        semantic=_SEMANTIC,
        technical_details=details,
        locale="ko",
    )

    assert artifact is not None
    block = cast(list[dict[str, object]], artifact["blocks"])[0]
    assert (block["slot_id"], block["kind"], block["title"]) == (
        "records",
        "table",
        "검증된 행",
    )
    data = cast(dict[str, object], block["data"])
    assert data["columns"][:4] == [
        {"key": "c0", "label": "name"},
        {"key": "c1", "label": "type"},
        {"key": "c2", "label": "observed_state"},
        {"key": "c3", "label": "state_concept"},
    ]


@pytest.mark.parametrize(
    ("output_shape", "row", "expected_labels"),
    (
        (
            "resource_health_list",
            {
                "name": "service-a",
                "type": "app-service",
                "observed_state": "unavailable",
                "health_concept": "resource_health.not_ready",
                "health_kind": "platform_initiated",
                "source_observed_at": "2026-08-21T11:00:00+00:00",
                "execution_authority": False,
            },
            [
                "name",
                "type",
                "observed_state",
                "health_concept",
                "health_kind",
                "source_observed_at",
            ],
        ),
        (
            "resource_metric_list",
            {
                "name": "service-a",
                "type": "container-app",
                "metric_concept": "resource.saturation",
                "value": 12000000.0,
                "unit": "nanocores",
                "window_end": "2026-08-21T11:00:00+00:00",
                "complete": True,
                "execution_authority": False,
            },
            ["name", "type", "metric_concept", "value", "unit", "window_end"],
        ),
    ),
)
def test_v2_collection_evidence_uses_bounded_verified_tables(
    output_shape: str,
    row: Mapping[str, object],
    expected_labels: list[str],
) -> None:
    artifact = compile_presentation_artifact_v2(
        semantic=_SEMANTIC,
        technical_details=_details([row], output_shape=output_shape),
        locale="en",
    )

    assert artifact is not None
    block = cast(list[dict[str, object]], artifact["blocks"])[0]
    assert (block["slot_id"], block["kind"]) == ("records", "table")
    data = cast(dict[str, object], block["data"])
    assert [item["label"] for item in cast(list[dict[str, str]], data["columns"])] == (
        expected_labels
    )


@pytest.mark.parametrize(
    ("output_shape", "row", "expected_labels"),
    (
        (
            "target_ingress_configuration",
            {
                "name": "app-example",
                "ingress_enabled": True,
                "external": True,
                "fqdn": "app.example.com",
                "target_port": 8080,
                "transport": "Auto",
                "allow_insecure": False,
                "traffic_rules": [{"latest_revision": True, "weight": 100}],
                "source_observed_at": "2026-08-22T00:59:00+00:00",
                "inventory_read_at": "2026-08-22T01:00:00+00:00",
                "execution_authority": False,
            },
            ["name", "ingress_enabled", "external", "fqdn", "target_port", "transport"],
        ),
        (
            "target_resource_metric",
            {
                "name": "app-example",
                "type": "compute.container-app",
                "metric_concept": "resource.memory.usage_pct",
                "value": 63.5,
                "unit": "percent",
                "aggregation": "average",
                "sample_count": 12,
                "window_start": "2026-08-15T01:00:00+00:00",
                "window_end": "2026-08-22T01:00:00+00:00",
                "complete": True,
                "evidence_refs": ["azure-metric:memory-percentage"],
                "execution_authority": False,
            },
            ["name", "type", "metric_concept", "value", "unit", "window_end"],
        ),
    ),
)
def test_v2_exact_target_outputs_preserve_the_requested_axis(
    output_shape: str,
    row: Mapping[str, object],
    expected_labels: list[str],
) -> None:
    artifact = compile_presentation_artifact_v2(
        semantic=_SEMANTIC,
        technical_details=_details([row], output_shape=output_shape),
        locale="en",
    )

    assert artifact is not None
    block = cast(list[dict[str, object]], artifact["blocks"])[0]
    assert (block["slot_id"], block["kind"]) == ("records", "table")
    data = cast(dict[str, object], block["data"])
    assert [item["label"] for item in cast(list[dict[str, str]], data["columns"])] == (
        expected_labels
    )
    assert "traffic_rules" not in str(data)
    assert "evidence_refs" not in str(data)


def test_v2_resource_event_history_uses_chronological_timeline() -> None:
    artifact = compile_presentation_artifact_v2(
        semantic=_SEMANTIC,
        technical_details=_details(
            [
                {
                    "occurred_at": "2026-08-21T10:00:00+00:00",
                    "name": "service-a",
                    "type": "container-app",
                    "event_kind": "availability_status",
                    "status": "unavailable",
                    "classification": "platform_initiated",
                },
                {
                    "occurred_at": "2026-08-21T10:05:00+00:00",
                    "name": "service-a",
                    "type": "container-app",
                    "event_kind": "resource_annotation",
                    "status": "downtime",
                    "classification": "customer_initiated",
                },
            ],
            output_shape="resource_event_history",
        ),
        locale="ko",
    )

    assert artifact is not None
    block = cast(list[dict[str, object]], artifact["blocks"])[0]
    assert (block["slot_id"], block["kind"], block["title"]) == (
        "timeline",
        "timeline",
        "검증된 타임라인",
    )
    data = cast(dict[str, object], block["data"])
    exact_table = cast(dict[str, object], data["exact_table"])
    assert [item["label"] for item in cast(list[dict[str, str]], exact_table["columns"])] == [
        "occurred_at",
        "name",
        "type",
        "event_kind",
        "status",
        "classification",
    ]


def test_v2_service_health_uses_active_event_timeline() -> None:
    artifact = compile_presentation_artifact_v2(
        semantic=_SEMANTIC,
        technical_details=_details(
            [
                {
                    "impact_start_at": "2026-08-21T10:00:00+00:00",
                    "event_type": "service_issue",
                    "title": "Regional connectivity issue",
                    "level": "warning",
                    "impacted_resource_count": 1,
                    "resource_name": "service-a",
                    "status": "active",
                    "execution_authority": False,
                },
                {
                    "impact_start_at": "2026-08-21T11:00:00+00:00",
                    "event_type": "planned_maintenance",
                    "title": "Planned maintenance",
                    "level": "informational",
                    "impacted_resource_count": 0,
                    "resource_name": None,
                    "status": "active",
                    "execution_authority": False,
                },
            ],
            output_shape="subscription_service_health",
        ),
        locale="ko",
    )

    assert artifact is not None
    block = cast(list[dict[str, object]], artifact["blocks"])[0]
    assert (block["slot_id"], block["kind"], block["title"]) == (
        "timeline",
        "timeline",
        "검증된 타임라인",
    )
    data = cast(dict[str, object], block["data"])
    exact_table = cast(dict[str, object], data["exact_table"])
    assert [item["label"] for item in cast(list[dict[str, str]], exact_table["columns"])] == [
        "impact_start_at",
        "event_type",
        "title",
        "level",
        "impacted_resource_count",
        "resource_name",
    ]


def test_v2_zero_resource_rows_render_typed_empty_evidence() -> None:
    artifact = compile_presentation_artifact_v2(
        semantic=_SEMANTIC,
        technical_details=_details([], output_shape="property_filtered_resources"),
        locale="en",
    )

    assert artifact is not None
    block = cast(list[dict[str, object]], artifact["blocks"])[0]
    assert (block["slot_id"], block["kind"], block["title"]) == (
        "records",
        "callout",
        "No matching evidence",
    )
    assert block["data"] == {
        "tone": "neutral",
        "lines": ["The verified query completed and returned 0 rows."],
    }


def test_v2_korean_temporal_zero_rows_render_completed_empty_evidence() -> None:
    artifact = compile_presentation_artifact_v2(
        semantic=_SEMANTIC,
        technical_details=_details(
            [],
            operation="select",
            output_shape="temporal_comparison",
        ),
        locale="ko",
    )

    assert artifact is not None
    block = cast(list[dict[str, object]], artifact["blocks"])[0]
    assert (block["slot_id"], block["kind"], block["title"]) == (
        "records",
        "callout",
        "일치하는 근거 없음",
    )
    assert block["data"] == {
        "tone": "neutral",
        "lines": ["검증된 조회가 완료되었고 0개 행을 반환했습니다."],
    }


def test_v2_resource_table_lifts_readable_fields_from_nested_property_bags() -> None:
    rows = [
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
    ]
    details = _details(
        rows,
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
    ]
    assert data["rows"] == [
        {
            "c0": "rg-fdai",
            "c1": "resource-group",
            "c2": "example-region",
        }
    ]
    assert cast(dict[str, object], rows[0])["id"] == "scope-1/resource-group/rg-fdai"
    assert cast(dict[str, object], rows[0])["object_type"] == "Resource"


def test_v2_resource_table_keeps_identity_when_no_readable_field_exists() -> None:
    details = _details(
        [{"id": "resource-a", "object_type": "Resource"}],
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
        {"key": "c0", "label": "id"},
        {"key": "c1", "label": "object_type"},
    ]
    assert data["rows"] == [{"c0": "resource-a", "c1": "Resource"}]


def test_v2_current_state_keeps_ready_revision_within_column_limit() -> None:
    details = _details(
        [
            {
                "execution_authority": False,
                "inventory_read_at": "2026-08-21T03:39:40+09:00",
                "name": "app-example",
                "provisioning_status": "Succeeded",
                "ready_revision_name": "app-example--ready",
                "revision_name": "app-example--new",
                "running_status": "Running",
                "source_observed_at": None,
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
        {"key": "c1", "label": "revision_name"},
        {"key": "c2", "label": "ready_revision_name"},
        {"key": "c3", "label": "running_status"},
        {"key": "c4", "label": "source_observed_at"},
        {"key": "c5", "label": "inventory_read_at"},
    ]
    assert data["rows"] == [
        {
            "c0": "app-example",
            "c1": "app-example--new",
            "c2": "app-example--ready",
            "c3": "Running",
            "c4": "-",
            "c5": "2026-08-21T03:39:40+09:00",
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
