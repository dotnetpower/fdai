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
_OPERATIONS = frozenset({"select", "compare", "explain_change", "validate", "action_draft"})
_OUTPUT_SHAPES = frozenset(
    {
        "aggregation_table",
        "causal_evidence",
        "evidence_validation",
        "ontology_manifest",
        "ontology_relationships",
        "property_filtered_resources",
        "resource_list",
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
    shape = analyze_evidence_shape(output, verified=_semantic_is_verified(semantic))
    intent = _presentation_intent(
        operation=cast(str, operation),
        output_shape=cast(str, output_shape),
        shape=shape,
    )
    decision = plan_presentation(intent=intent, shape=shape)
    block = _compile_block(decision.kind, shape=shape, locale=locale, evidence_refs=evidence_refs)
    if block is None:
        return None
    blocks = [block]
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
    if output_shape in {"resource_list", "property_filtered_resources"}:
        return PresentationIntent.EXACT
    return PresentationIntent.EXACT


def _compile_block(
    kind: PresentationKind,
    *,
    shape: EvidenceShape,
    locale: str,
    evidence_refs: list[object],
) -> JsonObject | None:
    korean = locale.casefold().startswith("ko")
    refs = cast(list[str], evidence_refs[:_MAX_REFS])
    exact_table = _exact_table(shape)
    base: dict[str, object] = {
        "emphasis": "primary",
        "collapsed": False,
        "evidence_refs": refs,
    }
    if kind is PresentationKind.CALLOUT:
        return cast(
            JsonObject,
            {
                **base,
                "slot_id": "limitations",
                "kind": "callout",
                "title": "사용 불가" if korean else "Unavailable",
                "data": {
                    "tone": "warning",
                    "lines": list(shape.limitations)
                    or [
                        "검증된 근거를 사용할 수 없습니다."
                        if korean
                        else "Verified evidence is unavailable."
                    ],
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


def _exact_table(shape: EvidenceShape) -> JsonObject | None:
    selected = shape.columns[:_MAX_COLUMNS]
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
