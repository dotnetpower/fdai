"""Generic channel-neutral blocks for verified semantic evidence."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import cast

from fdai_operator_service.families.conversation.contracts import JsonObject
from fdai_operator_service.families.conversation.presentation_planner import (
    EvidenceShape,
    PresentationKind,
    SemanticShape,
    VisualizationKind,
)

_MAX_COLUMNS = 6
_MAX_CELL_CHARS = 512
_MAX_REFS = 8


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
    if any(
        isinstance(value, float) and not math.isfinite(value)
        for record in shape.records
        for value in record.values()
    ):
        return None
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
