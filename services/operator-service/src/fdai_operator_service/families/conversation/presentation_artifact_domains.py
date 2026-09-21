"""Domain-specific verified semantic artifact layouts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from fdai_operator_service.families.conversation.contracts import JsonObject
from fdai_operator_service.families.conversation.presentation_artifact_renderers import (
    _compile_block,
)
from fdai_operator_service.families.conversation.presentation_artifact_v3 import (
    assemble_presentation_artifact_v3,
)
from fdai_operator_service.families.conversation.presentation_planner import (
    PresentationIntent,
    PresentationKind,
    VisualizationKind,
    analyze_evidence_shape,
    plan_presentation,
)

_MAX_CELL_CHARS = 512
_MAX_REFS = 8
_RESOURCE_STATE_COLUMNS = (
    "name",
    "resource_group",
    "region",
    "observed_state",
    "type",
    "source_observed_at",
)
_RESOURCE_HEALTH_COLUMNS = (
    "name",
    "type",
    "coverage_state",
    "availability_state",
    "provider_observed_at",
    "collection_completed_at",
)
_SERVICE_HEALTH_COLUMNS = (
    "impact_start_at",
    "event_type",
    "title",
    "level",
    "impacted_resource_count",
    "resource_name",
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
