"""Compile an accessible v2 artifact from verified semantic rows.

This compiler copies exact values only after the deterministic planner selects
one channel-neutral block. Vendor capability reduction remains downstream.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

from fdai_operator_service.families.conversation.contracts import JsonObject
from fdai_operator_service.families.conversation.presentation_planner import (
    EvidenceShape,
    PresentationIntent,
    PresentationKind,
    analyze_evidence_shape,
    plan_presentation,
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
    "observed_state",
    "health_concept",
    "health_kind",
    "source_observed_at",
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
        "resource_health_list",
        "resource_list",
        "resource_metric_list",
        "resource_state_list",
        "resource_target_candidates",
        "subscription_service_health",
        "target_error_activity_correlation",
        "target_health_assessment",
        "target_ingress_configuration",
        "target_resource_metric",
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
        or set(context) != {"operation", "output_shape"}
        or not isinstance(outputs, list)
        or len(outputs) != 1
        or not isinstance(outputs[0], Mapping)
        or not isinstance(evidence_refs, list)
        or not evidence_refs
        or any(not isinstance(item, str) for item in evidence_refs)
    ):
        return None
    operation = context.get("operation")
    output_shape = context.get("output_shape")
    if operation not in _OPERATIONS or output_shape not in _OUTPUT_SHAPES:
        return None
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
        return cast(
            JsonObject,
            {
                "schema_version": 2,
                "layout": "stack",
                "evidence_refs": evidence_refs[:_MAX_REFS],
                "blocks": blocks,
            },
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
        return cast(
            JsonObject,
            {
                "schema_version": 2,
                "layout": "stack",
                "evidence_refs": evidence_refs[:_MAX_REFS],
                "blocks": blocks,
            },
        )
    shape = analyze_evidence_shape(output, verified=_semantic_is_verified(semantic))
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
        evidence_refs=evidence_refs,
        preferred_columns=(_preferred_columns(cast(str, output_shape))),
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
    return cast(
        JsonObject,
        {
            "schema_version": 2,
            "layout": "stack",
            "evidence_refs": evidence_refs[:_MAX_REFS],
            "blocks": blocks,
        },
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


def _presentation_intent(
    *,
    operation: str,
    output_shape: str,
    shape: EvidenceShape,
) -> PresentationIntent:
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
        "resource_target_candidates": ("name", "type"),
        "subscription_service_health": _SERVICE_HEALTH_COLUMNS,
        "target_ingress_configuration": _RESOURCE_INGRESS_COLUMNS,
        "target_resource_metric": _RESOURCE_METRIC_COLUMNS,
    }.get(output_shape, ())


def _compile_block(
    kind: PresentationKind,
    *,
    reason_code: str,
    shape: EvidenceShape,
    locale: str,
    evidence_refs: list[object],
    preferred_columns: tuple[str, ...] = (),
) -> JsonObject | None:
    korean = locale.casefold().startswith("ko")
    refs = cast(list[str], evidence_refs[:_MAX_REFS])
    exact_table = _exact_table(shape, preferred_columns=preferred_columns)
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
    if exact_table is None:
        return None
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
        return _bar_block(shape, exact_table=exact_table, korean=korean, refs=refs, base=base)
    if kind is PresentationKind.COVERAGE:
        return _coverage_block(shape, exact_table=exact_table, korean=korean, refs=refs, base=base)
    if kind is PresentationKind.TIME_SERIES:
        return _time_series_block(
            shape, exact_table=exact_table, korean=korean, refs=refs, base=base
        )
    if kind is PresentationKind.COMPARISON:
        return _comparison_block(
            shape, exact_table=exact_table, korean=korean, refs=refs, base=base
        )
    if kind is PresentationKind.TIMELINE:
        return _timeline_block(shape, exact_table=exact_table, korean=korean, refs=refs, base=base)
    return None


def _bar_block(
    shape: EvidenceShape,
    *,
    exact_table: JsonObject,
    korean: bool,
    refs: list[str],
    base: Mapping[str, object],
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
) -> JsonObject | None:
    if (
        shape.timestamp_field is None
        or shape.metric_field is None
        or shape.current_field is None
        or len(shape.units) != 1
    ):
        return None
    metric = _cell(shape.records[0].get(shape.metric_field))
    return cast(
        JsonObject,
        {
            **base,
            "slot_id": "trend",
            "kind": "time_series",
            "title": "검증된 추세" if korean else "Verified trend",
            "evidence_refs": refs,
            "data": {
                "description": f"{metric} 메트릭의 정렬된 관찰값입니다."
                if korean
                else f"Ordered observations for the {metric} metric.",
                "metric": metric,
                "unit": shape.units[0],
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


def _comparison_block(
    shape: EvidenceShape,
    *,
    exact_table: JsonObject,
    korean: bool,
    refs: list[str],
    base: Mapping[str, object],
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


def _exact_table(
    shape: EvidenceShape,
    *,
    preferred_columns: tuple[str, ...] = (),
) -> JsonObject | None:
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
    return cleaned[:_MAX_CELL_CHARS] if cleaned else "-"


__all__ = ["compile_presentation_artifact_v2"]
