"""Compile an accessible v2 artifact from verified semantic rows.

This compiler copies exact values only after the deterministic planner selects
one channel-neutral block. Vendor capability reduction remains downstream.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

from fdai_operator_service.families.conversation.contracts import JsonObject
from fdai_operator_service.families.conversation.presentation_artifact_v3 import (
    PresentationLayout,
    assemble_presentation_artifact_v3,
)
from fdai_operator_service.families.conversation.presentation_planner import (
    EvidenceShape,
    PresentationIntent,
    PresentationKind,
    SemanticShape,
    VisualizationKind,
    analyze_evidence_shape,
    plan_presentation,
)
from fdai_operator_service.families.conversation.subscription_scope_presentation import (
    subscription_scope_artifact,
)

_MAX_COLUMNS = 6
_MAX_CELL_CHARS = 512
_MAX_REFS = 8
_RESOURCE_STATE_COLUMNS = (
    "name",
    "type",
    "observed_state",
    "state_concept",
    "source_observed_at",
    "inventory_read_at",
)
_RESOURCE_HEALTH_COLUMNS = (
    "name",
    "type",
    "coverage_state",
    "availability_state",
    "provider_observed_at",
    "collection_completed_at",
)
_RESOURCE_METRIC_COLUMNS = (
    "name",
    "type",
    "metric_concept",
    "value",
    "unit",
    "window_end",
)
_RESOURCE_EVENT_COLUMNS = (
    "occurred_at",
    "name",
    "type",
    "event_kind",
    "status",
    "classification",
)
_RESOURCE_INGRESS_COLUMNS = (
    "name",
    "ingress_enabled",
    "external",
    "fqdn",
    "target_port",
    "transport",
)
_SERVICE_HEALTH_COLUMNS = (
    "impact_start_at",
    "event_type",
    "title",
    "level",
    "impacted_resource_count",
    "resource_name",
)
_OPERATIONS = frozenset({"select", "compare", "explain_change", "validate", "action_draft"})
_OUTPUT_SHAPES = frozenset(
    {
        "aggregation_table",
        "causal_evidence",
        "evidence_validation",
        "ontology_manifest",
        "ontology_relationships",
        "property_filtered_resources",
        "resource_event_history",
        "resource_condition_sections",
        "resource_health_list",
        "resource_list",
        "resource_metric_list",
        "resource_state_list",
        "resource_state_transitions",
        "resource_target_candidates",
        "subscription_scope_identity",
        "subscription_service_health",
        "target_error_activity_correlation",
        "target_health_assessment",
        "target_ingress_configuration",
        "target_resource_metric",
        "target_resource_metric_series",
        "temporal_comparison",
        "topology_graph",
    }
)


def compile_presentation_artifact_v2(
    *,
    semantic: Mapping[str, object],
    technical_details: Mapping[str, object],
    locale: str,
) -> JsonObject | None:
    """Compile one v2 artifact or fail closed to canonical text."""
    context = technical_details.get("presentation_context")
    outputs = technical_details.get("outputs")
    evidence_refs = semantic.get("evidence_refs")
    if (
        not isinstance(context, Mapping)
        or set(context)
        not in (
            {"operation", "output_shape"},
            {"operation", "output_shape", "measure_concepts"},
            {"operation", "output_shape", "presentation_semantics"},
            {
                "operation",
                "output_shape",
                "measure_concepts",
                "presentation_semantics",
            },
        )
        or not isinstance(outputs, list)
        or not isinstance(evidence_refs, list)
        or not evidence_refs
        or len(evidence_refs) > _MAX_REFS
        or any(not isinstance(item, str) for item in evidence_refs)
    ):
        return None
    operation = context.get("operation")
    output_shape = context.get("output_shape")
    if operation not in _OPERATIONS or output_shape not in _OUTPUT_SHAPES:
        return None
    if output_shape == "resource_condition_sections":
        return _resource_condition_artifact(
            outputs=outputs,
            context=context,
            evidence_refs=cast(list[str], evidence_refs),
            locale=locale,
            verified=_semantic_is_verified(semantic),
        )
    if len(outputs) != 1 or not isinstance(outputs[0], Mapping):
        return None
    if output_shape == "subscription_scope_identity":
        return subscription_scope_artifact(
            output=cast(Mapping[str, object], outputs[0]),
            evidence_refs=cast(list[str], evidence_refs),
            locale=locale,
            verified=_semantic_is_verified(semantic),
        )
    if output_shape == "subscription_service_health":
        return _service_health_artifact(
            output=cast(Mapping[str, object], outputs[0]),
            evidence_refs=cast(list[str], evidence_refs),
            locale=locale,
            verified=_semantic_is_verified(semantic),
        )
    semantics = _presentation_semantics(context.get("presentation_semantics"))
    if context.get("presentation_semantics") is not None and semantics is None:
        return None
    semantic_shape, semantic_fields = semantics or (None, {})
    output = cast(Mapping[str, object], outputs[0])
    if isinstance(output.get("incident_profile"), Mapping):
        return None
    if output_shape == "target_error_activity_correlation":
        blocks = _error_activity_blocks(
            output,
            locale=locale,
            evidence_refs=evidence_refs,
            verified=_semantic_is_verified(semantic),
        )
        if blocks is None:
            return None
        return assemble_presentation_artifact_v3(
            layout="operational_brief",
            blocks=blocks,
            evidence_refs=cast(list[str], evidence_refs[:_MAX_REFS]),
            locale=locale,
            input_kinds=(
                "verified_semantic_result",
                "presentation_context",
                "operator_locale",
            ),
        )

    if output_shape == "target_health_assessment":
        blocks = _health_blocks(
            output,
            locale=locale,
            evidence_refs=evidence_refs,
            verified=_semantic_is_verified(semantic),
        )
        if blocks is None:
            return None
        return assemble_presentation_artifact_v3(
            layout="operational_brief",
            blocks=blocks,
            evidence_refs=cast(list[str], evidence_refs[:_MAX_REFS]),
            locale=locale,
            input_kinds=(
                "verified_semantic_result",
                "presentation_context",
                "operator_locale",
            ),
        )
    shape = analyze_evidence_shape(
        output,
        verified=_semantic_is_verified(semantic),
        semantic_shape=semantic_shape,
        semantic_fields=semantic_fields,
    )
    sampling_description: str | None = None
    if output_shape == "target_resource_metric_series" and shape.records:
        sampling = _metric_series_sampling(shape)
        if sampling is None:
            return None
        source_count, displayed_count, strategy = sampling
        sampling_description = _metric_series_sampling_description(
            source_count=source_count,
            displayed_count=displayed_count,
            strategy=strategy,
            korean=locale.casefold().startswith("ko"),
        )
    intent = _presentation_intent(
        operation=cast(str, operation),
        output_shape=cast(str, output_shape),
        shape=shape,
    )
    decision = plan_presentation(intent=intent, shape=shape)
    block = _compile_block(
        decision.kind,
        reason_code=decision.reason_code,
        shape=shape,
        locale=locale,
        evidence_refs=cast(list[object], evidence_refs),
        preferred_columns=(_preferred_columns(cast(str, output_shape))),
        time_series_description=sampling_description,
        visualization=decision.visualization,
    )
    if block is None:
        return None
    blocks = [block]
    if output_shape == "resource_target_candidates":
        overview = _target_candidates_overview(
            output,
            locale=locale,
            evidence_refs=evidence_refs,
        )
        if overview is None:
            return None
        blocks.insert(0, overview)
    limitation = _limitation_block(output, shape=shape, locale=locale, evidence_refs=evidence_refs)
    if limitation is not None and block["slot_id"] != "limitations":
        blocks.append(limitation)
    layout = _layout_for_output_shape(cast(str, output_shape))
    if layout is None:
        return cast(
            JsonObject,
            {
                "schema_version": 2,
                "layout": "stack",
                "evidence_refs": evidence_refs[:_MAX_REFS],
                "blocks": blocks,
            },
        )
    return assemble_presentation_artifact_v3(
        layout=layout,
        blocks=blocks,
        evidence_refs=cast(list[str], evidence_refs[:_MAX_REFS]),
        locale=locale,
        input_kinds=(
            "verified_semantic_result",
            "presentation_context",
            "operator_locale",
        ),
    )


def _resource_condition_artifact(
    *,
    outputs: list[object],
    context: Mapping[str, object],
    evidence_refs: list[str],
    locale: str,
    verified: bool,
) -> JsonObject | None:
    if len(outputs) != 2:
        return None
    by_node = {
        node_id: output
        for output in outputs
        if isinstance(output, Mapping) and isinstance((node_id := output.get("node_id")), str)
    }
    state_output = by_node.get("resource-condition-power")
    health_output = by_node.get("resource-condition-health")
    measures = context.get("measure_concepts")
    if (
        not isinstance(state_output, Mapping)
        or not isinstance(health_output, Mapping)
        or not isinstance(measures, list)
        or any(not isinstance(item, str) for item in measures)
    ):
        return None
    specs = (
        (
            "power_state",
            "전원 상태",
            "Power state",
            state_output,
            "state_concept",
            _RESOURCE_STATE_COLUMNS,
            "resource_state.",
        ),
        (
            "resource_health",
            "Resource Health",
            "Resource Health",
            health_output,
            "health_concept",
            _RESOURCE_HEALTH_COLUMNS,
            "resource_health.",
        ),
    )
    korean = locale.casefold().startswith("ko")
    summary_items: list[dict[str, object]] = []
    blocks: list[JsonObject] = []
    limitations: list[str] = []
    for slot, ko_title, en_title, output, concept_field, columns, prefix in specs:
        shape = analyze_evidence_shape(output, verified=verified)
        source_refs = output.get("evidence_refs")
        if not isinstance(source_refs, list) or any(
            not isinstance(item, str) for item in source_refs
        ):
            return None
        decision = plan_presentation(intent=PresentationIntent.EXACT, shape=shape)
        block = _compile_block(
            decision.kind,
            reason_code=decision.reason_code,
            shape=shape,
            locale=locale,
            evidence_refs=cast(list[object], source_refs),
            preferred_columns=columns,
            visualization=decision.visualization,
        )
        if block is None:
            return None
        block["slot_id"] = slot
        block["title"] = ko_title if korean else en_title
        blocks.append(block)
        complete = output.get("source_complete") is True
        display_complete = complete and output.get("display_truncated") is not True
        for concept in (item for item in measures if item.startswith(prefix)):
            matched = sum(
                1
                for row in shape.records
                if row.get(concept_field) == concept
                or (
                    concept_field == "health_concept"
                    and isinstance(
                        (matching_concepts := row.get("matching_health_concepts")),
                        list,
                    )
                    and concept in matching_concepts
                )
            )
            status = (
                "unresolved"
                if not verified
                else "matched"
                if matched
                else "verified_empty"
                if display_complete
                else "unresolved"
            )
            summary_items.append(
                {
                    "label": concept.rsplit(".", 1)[-1].replace("_", " "),
                    "value": status,
                    "tone": "warning" if status == "unresolved" else "neutral",
                }
            )
        limitation = output.get("source_truncation_reason")
        if isinstance(limitation, str) and limitation:
            limitations.append(f"{en_title}: {limitation}")
        if output.get("display_truncated") is True:
            limitations.append(f"{en_title}: display_truncated")
    blocks.insert(
        0,
        cast(
            JsonObject,
            {
                "slot_id": "overview",
                "kind": "summary",
                "title": "상태별 결론" if korean else "Per-condition conclusions",
                "emphasis": "primary",
                "collapsed": False,
                "evidence_refs": evidence_refs[:_MAX_REFS],
                "data": {"items": summary_items},
            },
        ),
    )
    if limitations:
        blocks.append(
            cast(
                JsonObject,
                {
                    "slot_id": "limitations",
                    "kind": "callout",
                    "title": "제한 사항" if korean else "Limitations",
                    "emphasis": "secondary",
                    "collapsed": False,
                    "evidence_refs": evidence_refs[:_MAX_REFS],
                    "data": {"tone": "warning", "lines": limitations},
                },
            )
        )
    return assemble_presentation_artifact_v3(
        layout="operational_brief",
        blocks=blocks,
        evidence_refs=evidence_refs[:_MAX_REFS],
        locale=locale,
        input_kinds=(
            "verified_semantic_result",
            "presentation_context",
            "operator_locale",
        ),
    )


def _service_health_artifact(
    *,
    output: Mapping[str, object],
    evidence_refs: list[str],
    locale: str,
    verified: bool,
) -> JsonObject | None:
    if not verified:
        return None
    rows = output.get("rows")
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], Mapping):
        return None
    summary = rows[0].get("values")
    if (
        not isinstance(summary, Mapping)
        or summary.get("record_kind") != "summary"
        or summary.get("scope_kind") != "subscription"
        or summary.get("execution_authority") is not False
    ):
        return None
    event_rows = [
        row
        for row in rows[1:]
        if isinstance(row, Mapping)
        and isinstance(row.get("values"), Mapping)
        and row["values"].get("record_kind") == "event"
    ]
    if len(event_rows) != len(rows) - 1:
        return None
    korean = locale.casefold().startswith("ko")
    complete = output.get("source_complete") is True
    event_count = summary.get("active_event_count")
    count_posture = summary.get("count_posture")
    if (
        event_count is not None
        and (not isinstance(event_count, int) or isinstance(event_count, bool) or event_count < 0)
    ) or count_posture not in {"exact", "minimum", "unknown"}:
        return None
    observed_event_count = event_count if isinstance(event_count, int) else 0
    conclusion = (
        "yes"
        if observed_event_count and complete
        else "yes_partial"
        if observed_event_count
        else "no"
        if complete
        else "unknown"
    )
    conclusion_labels = {
        "yes": ("활성 이벤트 있음", "Active events present"),
        "yes_partial": ("활성 이벤트 있음 - 범위 불완전", "Active events present - incomplete"),
        "no": ("활성 이벤트 없음", "No active events"),
        "unknown": ("활성 이벤트 여부 확인 불가", "Active event status unknown"),
    }
    blocks: list[JsonObject] = [
        cast(
            JsonObject,
            {
                "slot_id": "overview",
                "kind": "summary",
                "title": "Service Health 결론" if korean else "Service Health conclusion",
                "emphasis": "primary",
                "collapsed": False,
                "evidence_refs": evidence_refs[:_MAX_REFS],
                "data": {
                    "items": [
                        {
                            "label": "결론" if korean else "Conclusion",
                            "value": conclusion_labels[conclusion][0 if korean else 1],
                            "tone": (
                                "warning" if conclusion in {"yes_partial", "unknown"} else "neutral"
                            ),
                        },
                        {
                            "label": "고유 활성 이벤트" if korean else "Unique active events",
                            "value": (
                                str(observed_event_count)
                                if count_posture != "unknown"
                                else "unknown"
                            ),
                            "tone": "neutral",
                        },
                        {
                            "label": "영향 리소스" if korean else "Impacted resources",
                            "value": (
                                str(summary["impacted_resource_count"])
                                if summary.get("impacted_resource_count") is not None
                                else "unknown"
                            ),
                            "tone": "neutral",
                        },
                        {
                            "label": "관측 시각" if korean else "Observed at",
                            "value": str(summary.get("observed_at") or "unavailable"),
                            "tone": "neutral",
                        },
                    ]
                },
            },
        )
    ]
    total_rows = output.get("total_rows")
    total_event_rows = (
        max(0, total_rows - 1)
        if isinstance(total_rows, int) and not isinstance(total_rows, bool)
        else len(event_rows)
    )
    events_truncated = output.get("display_truncated") is True or (
        len(event_rows) < total_event_rows
    )
    event_output = {
        **output,
        "rows": event_rows,
        "returned_rows": len(event_rows),
        "total_rows": total_event_rows,
        "display_truncated": events_truncated,
    }
    shape = analyze_evidence_shape(event_output, verified=verified)
    event_block = _compile_block(
        PresentationKind.TIMELINE,
        reason_code="service_health_chronology",
        shape=shape,
        locale=locale,
        evidence_refs=cast(list[object], evidence_refs),
        preferred_columns=_SERVICE_HEALTH_COLUMNS,
        visualization=VisualizationKind.NONE,
    )
    if event_block is None:
        return None
    event_block["slot_id"] = "events"
    event_block["title"] = "활성 이벤트" if korean else "Active events"
    blocks.append(event_block)
    limitation = output.get("source_truncation_reason")
    limitation_lines = [limitation] if isinstance(limitation, str) and limitation else []
    if events_truncated:
        limitation_lines.append("display_truncated")
    if limitation_lines:
        blocks.append(
            cast(
                JsonObject,
                {
                    "slot_id": "limitations",
                    "kind": "callout",
                    "title": "제한 사항" if korean else "Limitations",
                    "emphasis": "secondary",
                    "collapsed": False,
                    "evidence_refs": evidence_refs[:_MAX_REFS],
                    "data": {"tone": "warning", "lines": limitation_lines},
                },
            )
        )
    return assemble_presentation_artifact_v3(
        layout="operational_brief",
        blocks=blocks,
        evidence_refs=evidence_refs[:_MAX_REFS],
        locale=locale,
        input_kinds=(
            "verified_semantic_result",
            "presentation_context",
            "operator_locale",
        ),
    )


def _layout_for_output_shape(output_shape: str) -> PresentationLayout | None:
    if output_shape in {"ontology_manifest", "ontology_relationships"}:
        return "markdown_document"
    return None


def _target_candidates_overview(
    output: Mapping[str, object],
    *,
    locale: str,
    evidence_refs: list[object],
) -> JsonObject | None:
    """Keep the exact-target selection step visible beside candidate rows."""

    total = output.get("total_rows")
    complete = output.get("source_complete")
    if not isinstance(total, int) or total < 0 or not isinstance(complete, bool):
        return None
    korean = locale.casefold().startswith("ko")
    return cast(
        JsonObject,
        {
            "slot_id": "overview",
            "kind": "summary",
            "title": "확인된 대상 후보" if korean else "Verified target candidates",
            "emphasis": "primary",
            "collapsed": False,
            "evidence_refs": cast(list[str], evidence_refs[:_MAX_REFS]),
            "data": {
                "items": [
                    {
                        "label": "검증된 후보" if korean else "Verified candidates",
                        "value": str(total),
                        "tone": "neutral",
                    },
                    {
                        "label": "범위 완전성" if korean else "Scope completeness",
                        "value": "complete" if complete else "incomplete",
                        "tone": "neutral" if complete else "attention",
                    },
                    {
                        "label": "다음 단계" if korean else "Next step",
                        "value": (
                            "표에서 확인할 리소스의 정확한 이름 또는 리소스 ID를 지정하세요."
                            if korean
                            else "Choose the exact resource name or resource ID from the table."
                        ),
                        "tone": "attention",
                    },
                ]
            },
        },
    )


def _health_blocks(
    output: Mapping[str, object],
    *,
    locale: str,
    evidence_refs: list[object],
    verified: bool,
) -> list[JsonObject] | None:
    if not verified:
        return None
    rows = output.get("rows")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        return None
    values = rows[0].get("values")
    if not isinstance(values, Mapping) or values.get("evidence_sufficient") is not False:
        return None
    if values.get("execution_authority") is not False:
        return None
    korean = locale.casefold().startswith("ko")
    refs = cast(list[str], evidence_refs[:_MAX_REFS])
    fields = (
        ("overall_assessment", "전체 평가", "Overall"),
        ("platform_lifecycle", "플랫폼 수명 주기", "Platform lifecycle"),
        ("readiness", "준비 상태", "Readiness"),
        ("application_service_health", "애플리케이션 서비스", "Application service"),
        ("stability", "안정성", "Stability"),
        ("resource_pressure", "리소스 압력", "Resource pressure"),
    )
    items = [
        {
            "label": korean_label if korean else english_label,
            "value": _health_cell(values.get(key)),
            "tone": "neutral",
        }
        for key, korean_label, english_label in fields
        if values.get(key) is not None
    ]
    if len(items) < 4:
        return None
    raw_gaps = values.get("evidence_gaps")
    gaps = (
        [item.strip().replace("_", " ") for item in raw_gaps.split(",") if item.strip()]
        if isinstance(raw_gaps, str)
        else []
    )
    freshness = [
        f"{label}: {value}"
        for label, value in (
            ("원본 관측" if korean else "Source observation", values.get("source_observed_at")),
            ("인벤토리 조회" if korean else "Inventory read", values.get("inventory_read_at")),
            ("메트릭 종료" if korean else "Metric window end", values.get("metric_window_end")),
        )
        if isinstance(value, str) and value
    ]
    lines = [*freshness, *gaps]
    return [
        cast(
            JsonObject,
            {
                "slot_id": "overview",
                "kind": "summary",
                "title": "건강 근거 평가" if korean else "Health evidence assessment",
                "emphasis": "primary",
                "collapsed": False,
                "evidence_refs": refs,
                "data": {"items": items},
            },
        ),
        cast(
            JsonObject,
            {
                "slot_id": "limitations",
                "kind": "callout",
                "title": "근거 공백" if korean else "Evidence gaps",
                "emphasis": "primary",
                "collapsed": False,
                "evidence_refs": refs,
                "data": {
                    "tone": "warning",
                    "lines": lines
                    or [
                        "검증된 freshness 또는 공백이 없습니다."
                        if korean
                        else "No verified freshness or gap detail is available."
                    ],
                },
            },
        ),
    ]


def _error_activity_blocks(
    output: Mapping[str, object],
    *,
    locale: str,
    evidence_refs: list[object],
    verified: bool,
) -> list[JsonObject] | None:
    if not verified:
        return None
    rows = output.get("rows")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        return None
    values = rows[0].get("values")
    if (
        not isinstance(values, Mapping)
        or values.get("causal_claim_supported") is not False
        or values.get("execution_authority") is not False
    ):
        return None
    korean = locale.casefold().startswith("ko")
    refs = cast(list[str], evidence_refs[:_MAX_REFS])
    fields = (
        ("error_trend", "요청 오류 추세", "Request error trend"),
        ("baseline_error_total", "직전 구간 오류", "Baseline errors"),
        ("current_error_total", "현재 구간 오류", "Current errors"),
        ("activity_state", "Activity Log", "Activity Log"),
        ("activity_change_count", "변경 이벤트", "Change events"),
        ("correlation_assessment", "상관 평가", "Correlation assessment"),
    )
    items = [
        {
            "label": korean_label if korean else english_label,
            "value": _health_cell(values.get(key)),
            "tone": "neutral",
        }
        for key, korean_label, english_label in fields
        if values.get(key) is not None
    ]
    if len(items) < 4:
        return None
    windows = [
        f"{label}: {value}"
        for label, value in (
            (
                "직전 구간 시작" if korean else "Baseline window start",
                values.get("baseline_window_start"),
            ),
            (
                "직전 구간 종료" if korean else "Baseline window end",
                values.get("baseline_window_end"),
            ),
            (
                "현재 구간 시작" if korean else "Current window start",
                values.get("current_window_start"),
            ),
            (
                "현재 구간 종료" if korean else "Current window end",
                values.get("current_window_end"),
            ),
        )
        if isinstance(value, str) and value
    ]
    raw_gaps = values.get("evidence_gaps")
    gaps = (
        [item.strip().replace("_", " ") for item in raw_gaps.split(",") if item.strip()]
        if isinstance(raw_gaps, str)
        else []
    )
    caution = (
        "같은 구간의 동시 관측은 인과관계를 입증하지 않습니다."
        if korean
        else "Co-occurrence in the same window does not establish causation."
    )
    return [
        cast(
            JsonObject,
            {
                "slot_id": "overview",
                "kind": "summary",
                "title": (
                    "요청 오류와 Activity Log 상관 평가"
                    if korean
                    else "Request errors and Activity Log correlation"
                ),
                "emphasis": "primary",
                "collapsed": False,
                "evidence_refs": refs,
                "data": {"items": items},
            },
        ),
        cast(
            JsonObject,
            {
                "slot_id": "limitations",
                "kind": "callout",
                "title": "근거 구간과 공백" if korean else "Evidence windows and gaps",
                "emphasis": "primary",
                "collapsed": False,
                "evidence_refs": refs,
                "data": {
                    "tone": "warning" if gaps else "neutral",
                    "lines": [*windows, *gaps, caution],
                },
            },
        ),
    ]


def _health_cell(value: object) -> str:
    if isinstance(value, str) and value:
        return value.replace("_", " ")[:_MAX_CELL_CHARS]
    if isinstance(value, bool):
        return "true" if value else "false"
    return "not proven"


def _presentation_intent(
    *,
    operation: str,
    output_shape: str,
    shape: EvidenceShape,
) -> PresentationIntent:
    if shape.semantic_shape is SemanticShape.CORRELATION:
        return PresentationIntent.CORRELATION
    if shape.semantic_shape is SemanticShape.CATEGORICAL_MATRIX:
        return PresentationIntent.MATRIX
    if output_shape == "target_resource_metric_series":
        return PresentationIntent.TREND
    if output_shape == "temporal_comparison":
        return (
            PresentationIntent.TREND if len(shape.records) >= 3 else PresentationIntent.COMPARISON
        )
    if operation == "compare":
        return PresentationIntent.COMPARISON
    if output_shape == "aggregation_table":
        if shape.threshold_field is not None:
            return PresentationIntent.THRESHOLD
        if shape.numerator_field is not None and shape.denominator_field is not None:
            return PresentationIntent.COVERAGE
        if shape.category_field is not None and shape.current_field is not None:
            return PresentationIntent.DISTRIBUTION
        return PresentationIntent.SUMMARY if len(shape.records) == 1 else PresentationIntent.EXACT
    if output_shape == "topology_graph" and shape.timestamp_field is not None:
        return PresentationIntent.CHRONOLOGY
    if output_shape == "resource_event_history":
        return PresentationIntent.CHRONOLOGY
    if output_shape == "resource_state_transitions":
        return PresentationIntent.CHRONOLOGY
    if output_shape == "subscription_service_health":
        return PresentationIntent.CHRONOLOGY
    if output_shape in {
        "resource_health_list",
        "resource_list",
        "resource_metric_list",
        "property_filtered_resources",
        "resource_state_list",
        "resource_target_candidates",
    }:
        return PresentationIntent.EXACT
    return PresentationIntent.EXACT


def _preferred_columns(output_shape: str) -> tuple[str, ...]:
    return {
        "resource_event_history": _RESOURCE_EVENT_COLUMNS,
        "resource_health_list": _RESOURCE_HEALTH_COLUMNS,
        "resource_metric_list": _RESOURCE_METRIC_COLUMNS,
        "resource_state_list": _RESOURCE_STATE_COLUMNS,
        "resource_state_transitions": (
            "effective_at",
            "name",
            "state_type",
            "from_state",
            "to_state",
            "source_identity",
        ),
        "resource_target_candidates": ("name", "type"),
        "subscription_service_health": _SERVICE_HEALTH_COLUMNS,
        "target_ingress_configuration": _RESOURCE_INGRESS_COLUMNS,
        "target_resource_metric": _RESOURCE_METRIC_COLUMNS,
        "target_resource_metric_series": ("timestamp", "value", "unit", "metric"),
    }.get(output_shape, ())


def _compile_block(
    kind: PresentationKind,
    *,
    reason_code: str,
    shape: EvidenceShape,
    locale: str,
    evidence_refs: list[object],
    preferred_columns: tuple[str, ...] = (),
    time_series_description: str | None = None,
    visualization: VisualizationKind = VisualizationKind.NONE,
) -> JsonObject | None:
    korean = locale.casefold().startswith("ko")
    refs = cast(list[str], evidence_refs[:_MAX_REFS])
    base: dict[str, object] = {
        "emphasis": "primary",
        "collapsed": False,
        "evidence_refs": refs,
    }
    if kind is PresentationKind.CALLOUT:
        verified_empty = reason_code == "verified_empty_result"
        return cast(
            JsonObject,
            {
                **base,
                "slot_id": "records" if verified_empty else "limitations",
                "kind": "callout",
                "title": (
                    "일치하는 근거 없음"
                    if korean and verified_empty
                    else "No matching evidence"
                    if verified_empty
                    else "사용 불가"
                    if korean
                    else "Unavailable"
                ),
                "data": {
                    "tone": "neutral" if verified_empty else "warning",
                    "lines": (
                        [
                            "검증된 조회가 완료되었고 0개 행을 반환했습니다."
                            if korean
                            else "The verified query completed and returned 0 rows."
                        ]
                        if verified_empty
                        else list(shape.limitations)
                        or [
                            "검증된 근거를 사용할 수 없습니다."
                            if korean
                            else "Verified evidence is unavailable."
                        ]
                    ),
                },
            },
        )
    if kind is PresentationKind.SUMMARY:
        record = shape.records[0]
        return cast(
            JsonObject,
            {
                **base,
                "slot_id": "overview",
                "kind": "summary",
                "title": "검증된 요약" if korean else "Verified summary",
                "data": {
                    "items": [
                        {"label": field, "value": _cell(record.get(field)), "tone": "neutral"}
                        for field in shape.columns[:8]
                    ]
                },
            },
        )
    exact_table = _exact_table(shape, preferred_columns=preferred_columns)
    if exact_table is None:
        return None
    if kind in {PresentationKind.TABLE, PresentationKind.LIST, PresentationKind.THRESHOLD_TABLE}:
        slot = "metrics" if kind is PresentationKind.THRESHOLD_TABLE else "records"
        title = (
            "임계값 비교"
            if korean and kind is PresentationKind.THRESHOLD_TABLE
            else "Threshold comparison"
            if kind is PresentationKind.THRESHOLD_TABLE
            else "검증된 행"
            if korean
            else "Verified rows"
        )
        return cast(
            JsonObject,
            {
                **base,
                "slot_id": slot,
                "kind": kind.value,
                "title": title,
                "data": exact_table,
            },
        )
    if kind is PresentationKind.BAR:
        return _bar_block(
            shape,
            exact_table=exact_table,
            korean=korean,
            refs=refs,
            base=base,
            visualization=visualization,
        )
    if kind is PresentationKind.COVERAGE:
        return _coverage_block(
            shape,
            exact_table=exact_table,
            korean=korean,
            refs=refs,
            base=base,
            visualization=visualization,
        )
    if kind is PresentationKind.TIME_SERIES:
        return _time_series_block(
            shape,
            exact_table=exact_table,
            korean=korean,
            refs=refs,
            base=base,
            sampling_description=time_series_description,
            visualization=visualization,
        )
    if kind is PresentationKind.COMPARISON:
        return _comparison_block(
            shape,
            exact_table=exact_table,
            korean=korean,
            refs=refs,
            base=base,
            visualization=visualization,
        )
    if kind is PresentationKind.TIMELINE:
        return _timeline_block(
            shape,
            exact_table=exact_table,
            korean=korean,
            refs=refs,
            base=base,
            visualization=visualization,
        )
    if kind is PresentationKind.SCATTER:
        return _scatter_block(shape, exact_table=exact_table, korean=korean, refs=refs, base=base)
    if kind is PresentationKind.HEATMAP:
        return _heatmap_block(shape, exact_table=exact_table, korean=korean, refs=refs, base=base)
    return None


def _bar_block(
    shape: EvidenceShape,
    *,
    exact_table: JsonObject,
    korean: bool,
    refs: list[str],
    base: Mapping[str, object],
    visualization: VisualizationKind,
) -> JsonObject | None:
    if shape.category_field is None or shape.current_field is None or len(shape.units) != 1:
        return None
    return cast(
        JsonObject,
        {
            **base,
            "slot_id": "distribution",
            "kind": "bar",
            "title": "검증된 분포" if korean else "Verified distribution",
            "evidence_refs": refs,
            "data": {
                "description": "같은 단위의 범주 값을 비교합니다."
                if korean
                else "Compares categorical values with one unit.",
                "unit": shape.units[0],
                "visualization": visualization.value,
                "items": [
                    {
                        "label": _cell(record.get(shape.category_field)),
                        "value": record[shape.current_field],
                        "tone": "neutral",
                    }
                    for record in shape.records
                ],
                "exact_table": exact_table,
            },
        },
    )


def _coverage_block(
    shape: EvidenceShape,
    *,
    exact_table: JsonObject,
    korean: bool,
    refs: list[str],
    base: Mapping[str, object],
    visualization: VisualizationKind,
) -> JsonObject | None:
    if shape.numerator_field is None or shape.denominator_field is None:
        return None
    label_field = shape.category_field or shape.numerator_field
    return cast(
        JsonObject,
        {
            **base,
            "slot_id": "coverage",
            "kind": "coverage",
            "title": "검증된 커버리지" if korean else "Verified coverage",
            "evidence_refs": refs,
            "data": {
                "description": "검증된 분자와 분모를 비교합니다."
                if korean
                else "Compares verified numerators and denominators.",
                "unit": "ratio",
                "visualization": visualization.value,
                "items": [
                    {
                        "label": _cell(record.get(label_field)),
                        "value": record[shape.numerator_field],
                        "total": record[shape.denominator_field],
                        "tone": "neutral",
                    }
                    for record in shape.records
                ],
                "exact_table": exact_table,
            },
        },
    )


def _time_series_block(
    shape: EvidenceShape,
    *,
    exact_table: JsonObject,
    korean: bool,
    refs: list[str],
    base: Mapping[str, object],
    sampling_description: str | None,
    visualization: VisualizationKind,
) -> JsonObject | None:
    if (
        shape.timestamp_field is None
        or shape.metric_field is None
        or shape.current_field is None
        or len(shape.units) != 1
    ):
        return None
    metric = _cell(shape.records[0].get(shape.metric_field))
    description = (
        f"{metric} 메트릭의 정렬된 관찰값입니다."
        if korean
        else f"Ordered observations for the {metric} metric."
    )
    if sampling_description is not None:
        description = f"{description} {sampling_description}"
    return cast(
        JsonObject,
        {
            **base,
            "slot_id": "trend",
            "kind": "time_series",
            "title": "검증된 추세" if korean else "Verified trend",
            "evidence_refs": refs,
            "data": {
                "description": description,
                "metric": metric,
                "unit": shape.units[0],
                "visualization": visualization.value,
                "points": [
                    {
                        "timestamp": record[shape.timestamp_field],
                        "value": record[shape.current_field],
                    }
                    for record in shape.records
                ],
                "exact_table": exact_table,
            },
        },
    )


def _metric_series_sampling(shape: EvidenceShape) -> tuple[int, int, str] | None:
    fields = ("source_sample_count", "displayed_sample_count", "sampling_strategy")
    metadata = {tuple(record.get(field) for field in fields) for record in shape.records}
    if len(metadata) != 1:
        return None
    source_count, displayed_count, strategy = next(iter(metadata))
    if (
        not isinstance(source_count, int)
        or isinstance(source_count, bool)
        or not isinstance(displayed_count, int)
        or isinstance(displayed_count, bool)
        or not isinstance(strategy, str)
        or displayed_count != len(shape.records)
        or not 3 <= displayed_count <= 40
        or source_count < displayed_count
    ):
        return None
    if strategy == "none" and source_count == displayed_count:
        return source_count, displayed_count, strategy
    if strategy == "min_max_envelope_v1" and source_count > displayed_count:
        return source_count, displayed_count, strategy
    return None


def _metric_series_sampling_description(
    *,
    source_count: int,
    displayed_count: int,
    strategy: str,
    korean: bool,
) -> str:
    if strategy == "none":
        return (
            f"검증된 provider 표본 {source_count}개를 모두 표시합니다."
            if korean
            else f"Displays all {source_count} verified provider samples."
        )
    return (
        f"검증된 provider 표본 {source_count}개 중 양 끝점과 구간별 최솟값/최댓값 "
        f"{displayed_count}개를 표시합니다."
        if korean
        else f"Displays {displayed_count} endpoint and min/max envelope points from "
        f"{source_count} verified provider samples."
    )


def _comparison_block(
    shape: EvidenceShape,
    *,
    exact_table: JsonObject,
    korean: bool,
    refs: list[str],
    base: Mapping[str, object],
    visualization: VisualizationKind,
) -> JsonObject | None:
    if len(shape.units) != 1:
        return None
    record = shape.records[0]
    roles = (
        ("baseline", shape.baseline_field),
        ("current", shape.current_field),
        ("target", shape.target_field),
    )
    items = [
        {"role": role, "label": role, "value": record[field]}
        for role, field in roles
        if field is not None
    ]
    if len(items) < 2:
        return None
    metric = _cell(record.get(shape.metric_field)) if shape.metric_field else "value"
    return cast(
        JsonObject,
        {
            **base,
            "slot_id": "comparison",
            "kind": "comparison",
            "title": "검증된 비교" if korean else "Verified comparison",
            "evidence_refs": refs,
            "data": {
                "description": f"{metric}의 역할별 값을 비교합니다."
                if korean
                else f"Compares role-bound values for {metric}.",
                "metric": metric,
                "unit": shape.units[0],
                "visualization": visualization.value,
                "items": items,
                "exact_table": exact_table,
            },
        },
    )


def _timeline_block(
    shape: EvidenceShape,
    *,
    exact_table: JsonObject,
    korean: bool,
    refs: list[str],
    base: Mapping[str, object],
    visualization: VisualizationKind,
) -> JsonObject | None:
    if shape.timestamp_field is None:
        return None
    label_field = next(
        (field for field in ("event", "activity", "label", "status") if field in shape.columns),
        None,
    )
    if label_field is None:
        return None
    return cast(
        JsonObject,
        {
            **base,
            "slot_id": "timeline",
            "kind": "timeline",
            "title": "검증된 타임라인" if korean else "Verified timeline",
            "evidence_refs": refs,
            "data": {
                "description": "근거가 되는 순서를 보존합니다."
                if korean
                else "Preserves the evidence-bearing order.",
                "visualization": visualization.value,
                "items": [
                    {
                        "timestamp": record[shape.timestamp_field],
                        "label": _cell(record.get(label_field)),
                    }
                    for record in shape.records
                ],
                "exact_table": exact_table,
            },
        },
    )


def _scatter_block(
    shape: EvidenceShape,
    *,
    exact_table: JsonObject,
    korean: bool,
    refs: list[str],
    base: Mapping[str, object],
) -> JsonObject | None:
    fields = dict(shape.semantic_fields)
    x_field = fields.get("x")
    y_field = fields.get("y")
    label_field = fields.get("label") or shape.category_field
    if x_field not in shape.numeric_fields or y_field not in shape.numeric_fields:
        return None
    return cast(
        JsonObject,
        {
            **base,
            "slot_id": "correlation",
            "kind": "scatter",
            "title": "검증된 상관관계" if korean else "Verified correlation",
            "evidence_refs": refs,
            "data": {
                "description": "두 검증된 수치 축을 비교합니다."
                if korean
                else "Compares two verified numeric axes.",
                "x_label": x_field,
                "y_label": y_field,
                "points": [
                    {
                        "label": _cell(record.get(label_field)) if label_field else str(index + 1),
                        "x": record[x_field],
                        "y": record[y_field],
                    }
                    for index, record in enumerate(shape.records)
                ],
                "exact_table": exact_table,
            },
        },
    )


def _heatmap_block(
    shape: EvidenceShape,
    *,
    exact_table: JsonObject,
    korean: bool,
    refs: list[str],
    base: Mapping[str, object],
) -> JsonObject | None:
    fields = dict(shape.semantic_fields)
    row_field = fields.get("row")
    column_field = fields.get("column")
    value_field = fields.get("value")
    if not row_field or not column_field or value_field not in shape.numeric_fields:
        return None
    return cast(
        JsonObject,
        {
            **base,
            "slot_id": "matrix",
            "kind": "heatmap",
            "title": "검증된 행렬" if korean else "Verified matrix",
            "evidence_refs": refs,
            "data": {
                "description": "두 범주 차원의 검증된 값을 비교합니다."
                if korean
                else "Compares verified values across two categorical dimensions.",
                "row_label": row_field,
                "column_label": column_field,
                "cells": [
                    {
                        "row": _cell(record.get(row_field)),
                        "column": _cell(record.get(column_field)),
                        "value": record[value_field],
                    }
                    for record in shape.records
                ],
                "exact_table": exact_table,
            },
        },
    )


def _presentation_semantics(
    raw: object,
) -> tuple[SemanticShape, dict[str, str]] | None:
    if not isinstance(raw, Mapping) or set(raw) != {"shape", "fields"}:
        return None
    raw_shape = raw.get("shape")
    if not isinstance(raw_shape, str):
        return None
    try:
        shape = SemanticShape(raw_shape)
    except ValueError:
        return None
    fields = raw.get("fields")
    if not isinstance(fields, Mapping) or any(
        not isinstance(key, str) or not isinstance(value, str) or not key or not value
        for key, value in fields.items()
    ):
        return None
    parsed_fields = cast(dict[str, str], dict(fields))
    expected_fields = {
        SemanticShape.CORRELATION: {"label", "x", "y"},
        SemanticShape.CATEGORICAL_MATRIX: {"row", "column", "value"},
    }.get(shape, set())
    if set(parsed_fields) != expected_fields or len(set(parsed_fields.values())) != len(
        parsed_fields
    ):
        return None
    return shape, parsed_fields


def _exact_table(
    shape: EvidenceShape,
    *,
    preferred_columns: tuple[str, ...] = (),
) -> JsonObject | None:
    if any(len(field) > _MAX_CELL_CHARS for field in shape.columns) or any(
        len(_render_cell(record.get(field))) > _MAX_CELL_CHARS
        for record in shape.records
        for field in shape.columns
    ):
        return None
    selected = tuple(
        [field for field in preferred_columns if field in shape.columns]
        + [field for field in shape.columns if field not in preferred_columns]
    )[:_MAX_COLUMNS]
    if not selected or not shape.records:
        return None
    return cast(
        JsonObject,
        {
            "columns": [
                {"key": f"c{index}", "label": field} for index, field in enumerate(selected)
            ],
            "rows": [
                {f"c{index}": _cell(record.get(field)) for index, field in enumerate(selected)}
                for record in shape.records
            ],
            "status_key": None,
        },
    )


def _limitation_block(
    output: Mapping[str, object],
    *,
    shape: EvidenceShape,
    locale: str,
    evidence_refs: list[object],
) -> JsonObject | None:
    lines = list(shape.limitations)
    returned = output.get("returned_rows")
    total = output.get("total_rows")
    korean = locale.casefold().startswith("ko")
    if isinstance(returned, int) and isinstance(total, int) and returned < total:
        lines.append(
            f"검증된 {total}개 행 중 {returned}개를 표시합니다."
            if korean
            else f"{returned} of {total} verified rows are shown."
        )
    if shape.missing_values:
        lines.append(
            "누락된 값은 추론하지 않았습니다." if korean else "Missing values were not inferred."
        )
    if not lines:
        return None
    return cast(
        JsonObject,
        {
            "slot_id": "limitations",
            "kind": "callout",
            "title": "제한 사항" if korean else "Limitations",
            "emphasis": "supporting",
            "collapsed": False,
            "evidence_refs": cast(list[str], evidence_refs[:_MAX_REFS]),
            "data": {"tone": "warning", "lines": list(dict.fromkeys(lines))[:16]},
        },
    )


def _semantic_is_verified(semantic: Mapping[str, object]) -> bool:
    completed = semantic.get("checks_completed")
    total = semantic.get("checks_total")
    return (
        semantic.get("disposition") == "answered"
        and isinstance(completed, int)
        and not isinstance(completed, bool)
        and isinstance(total, int)
        and not isinstance(total, bool)
        and completed == total
        and total > 0
    )


def _cell(value: object) -> str:
    return _render_cell(value)[:_MAX_CELL_CHARS]


def _render_cell(value: object) -> str:
    if value is None:
        rendered = ""
    elif isinstance(value, str):
        rendered = value
    elif isinstance(value, bool):
        rendered = "true" if value else "false"
    elif isinstance(value, int | float):
        rendered = str(value)
    else:
        rendered = json.dumps(value, allow_nan=False, ensure_ascii=False, sort_keys=True)
    cleaned = "".join(
        " " if ord(character) < 32 or ord(character) == 127 else character for character in rendered
    ).strip()
    return cleaned if cleaned else "-"


__all__ = ["compile_presentation_artifact_v2"]
