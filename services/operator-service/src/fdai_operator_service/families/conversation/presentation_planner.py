"""Select channel-neutral presentation blocks from verified evidence shape.

The planner classifies typed rows only. It does not read prose, choose a vendor
component, or copy values into a wire artifact. Callers compile exact values
after this module returns a bounded deterministic decision.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from numbers import Real
from types import MappingProxyType
from typing import cast

from fdai_operator_service.families.conversation.presentation_rows import (
    ordered_columns,
    readable_row,
)


class PresentationIntent(StrEnum):
    """Verified question intent relevant to presentation selection."""

    SUMMARY = "summary"
    EXACT = "exact"
    AUDIT = "audit"
    DISTRIBUTION = "distribution"
    COVERAGE = "coverage"
    THRESHOLD = "threshold"
    TREND = "trend"
    COMPARISON = "comparison"
    CHRONOLOGY = "chronology"
    RECORDS = "records"
    CORRELATION = "correlation"
    MATRIX = "matrix"


class PresentationKind(StrEnum):
    """Closed channel-neutral block kinds emitted by the planner."""

    SUMMARY = "summary"
    TABLE = "table"
    THRESHOLD_TABLE = "threshold_table"
    LIST = "list"
    COVERAGE = "coverage"
    BAR = "bar"
    TIME_SERIES = "time_series"
    COMPARISON = "comparison"
    TIMELINE = "timeline"
    CALLOUT = "callout"
    EVIDENCE = "evidence"
    SCATTER = "scatter"
    HEATMAP = "heatmap"


class SemanticShape(StrEnum):
    """Ontology-grounded relationship between verified dimensions and measures."""

    CATEGORICAL_COMPARISON = "categorical_comparison"
    CATEGORICAL_MATRIX = "categorical_matrix"
    CHRONOLOGY = "chronology"
    CORRELATION = "correlation"
    COVERAGE = "coverage"
    CUMULATIVE_SERIES = "cumulative_series"
    PART_TO_WHOLE = "part_to_whole"
    RANKING = "ranking"
    ROLE_COMPARISON = "role_comparison"
    TEMPORAL_SERIES = "temporal_series"


class VisualizationKind(StrEnum):
    """Closed renderer-neutral visualization hints emitted by the planner."""

    NONE = "none"
    AREA = "area"
    BAR = "bar"
    BAR_LIST = "bar_list"
    CATEGORY_BAR = "category_bar"
    COMPARISON_BAR = "comparison_bar"
    DONUT = "donut"
    HEATMAP = "heatmap"
    LINE = "line"
    SCATTER = "scatter"
    TRACKER = "tracker"


@dataclass(frozen=True, slots=True)
class EvidenceShape:
    """Bounded structural facts derived from one verified query output."""

    records: tuple[Mapping[str, object], ...]
    columns: tuple[str, ...]
    numeric_fields: tuple[str, ...]
    timestamp_field: str | None
    metric_field: str | None
    unit_field: str | None
    category_field: str | None
    baseline_field: str | None
    current_field: str | None
    target_field: str | None
    threshold_field: str | None
    status_field: str | None
    numerator_field: str | None
    denominator_field: str | None
    units: tuple[str, ...]
    complete: bool
    verified: bool
    timestamps_ordered: bool
    missing_values: bool
    heterogeneous: bool
    unavailable: bool
    limitations: tuple[str, ...]
    semantic_shape: SemanticShape | None
    semantic_fields: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class PresentationDecision:
    """One deterministic block choice plus its exact-value fallback policy."""

    kind: PresentationKind
    fallback_kind: PresentationKind
    reason_code: str
    include_exact_table: bool = False
    visualization: VisualizationKind = VisualizationKind.NONE


_TIMESTAMP_FIELDS = (
    "timestamp",
    "impact_start_at",
    "occurred_at",
    "recorded_at",
    "observed_at",
    "time",
    "ts",
)
_METRIC_FIELDS = ("metric", "metric_name", "concept_id")
_UNIT_FIELDS = ("unit", "canonical_unit")
_CATEGORY_FIELDS = ("category", "label", "name", "type", "status", "location")
_BASELINE_FIELDS = ("baseline", "baseline_value", "before")
_CURRENT_FIELDS = (
    "current",
    "current_value",
    "cumulative_value",
    "observed",
    "value",
    "after",
)
_TARGET_FIELDS = ("target", "target_value")
_THRESHOLD_FIELDS = ("threshold", "threshold_value")
_STATUS_FIELDS = ("status", "state", "outcome")
_NUMERATOR_FIELDS = ("numerator", "covered", "observed_count")
_DENOMINATOR_FIELDS = ("denominator", "total", "total_count")
_MAX_ANALYZED_ROWS = 40
_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


def analyze_evidence_shape(
    output: Mapping[str, object],
    *,
    verified: bool,
    semantic_shape: SemanticShape | None = None,
    semantic_fields: Mapping[str, str] | None = None,
) -> EvidenceShape:
    """Analyze bounded row shape without inferring or coercing missing values."""
    raw_rows = output.get("rows")
    records: list[Mapping[str, object]] = []
    columns: list[str] = []
    if isinstance(raw_rows, list) and len(raw_rows) <= _MAX_ANALYZED_ROWS:
        for raw_row in raw_rows:
            values = raw_row.get("values") if isinstance(raw_row, Mapping) else None
            if not isinstance(values, Mapping):
                records = []
                columns = []
                break
            record = readable_row(values)
            records.append(MappingProxyType(record))
            for key in record:
                if key not in columns:
                    columns.append(key)

    columns = ordered_columns(columns)

    returned_rows = output.get("returned_rows")
    total_rows = output.get("total_rows")
    counts_valid = (
        _is_non_negative_int(returned_rows)
        and _is_non_negative_int(total_rows)
        and returned_rows == len(records)
    )
    complete = bool(counts_valid and returned_rows == total_rows)
    numeric_fields = tuple(
        field
        for field in columns
        if records and all(_is_finite_number(record.get(field)) for record in records)
    )
    timestamp_field = _first_field(columns, _TIMESTAMP_FIELDS)
    metric_field = _first_field(columns, _METRIC_FIELDS)
    unit_field = _first_field(columns, _UNIT_FIELDS)
    units = _string_values(records, unit_field)
    limitations = _limitations(output)
    missing_values = any(
        field not in record or record[field] is None for record in records for field in columns
    )
    timestamps_ordered = _timestamps_are_ordered(records, timestamp_field)
    key_sets = {tuple(sorted(record)) for record in records}
    unavailable = bool(output.get("unavailable") is True or output.get("available") is False)
    return EvidenceShape(
        records=tuple(records),
        columns=tuple(columns),
        numeric_fields=numeric_fields,
        timestamp_field=timestamp_field,
        metric_field=metric_field,
        unit_field=unit_field,
        category_field=_first_field(columns, _CATEGORY_FIELDS),
        baseline_field=_first_field(columns, _BASELINE_FIELDS),
        current_field=_first_field(columns, _CURRENT_FIELDS),
        target_field=_first_field(columns, _TARGET_FIELDS),
        threshold_field=_first_field(columns, _THRESHOLD_FIELDS),
        status_field=_first_field(columns, _STATUS_FIELDS),
        numerator_field=_first_field(columns, _NUMERATOR_FIELDS),
        denominator_field=_first_field(columns, _DENOMINATOR_FIELDS),
        units=units,
        complete=complete,
        verified=verified,
        timestamps_ordered=timestamps_ordered,
        missing_values=missing_values,
        heterogeneous=len(key_sets) > 1,
        unavailable=unavailable,
        limitations=limitations,
        semantic_shape=semantic_shape,
        semantic_fields=tuple(sorted((semantic_fields or {}).items())),
    )


def plan_presentation(
    *,
    intent: PresentationIntent,
    shape: EvidenceShape,
) -> PresentationDecision:
    """Select the smallest loss-bounded block justified by verified shape."""
    if not shape.verified:
        return _decision(PresentationKind.CALLOUT, "verification_incomplete")
    if shape.unavailable:
        return _decision(PresentationKind.CALLOUT, "evidence_unavailable")
    if not shape.records:
        return _decision(
            PresentationKind.CALLOUT,
            "verified_empty_result" if shape.complete else "evidence_unavailable",
        )
    if shape.limitations or not shape.complete:
        return _fallback_for_records(shape, "evidence_incomplete")
    if shape.missing_values and not (
        intent is PresentationIntent.CHRONOLOGY and _supports_timeline(shape)
    ):
        return _fallback_for_records(shape, "evidence_incomplete")

    if shape.semantic_shape is SemanticShape.CORRELATION and _supports_scatter(shape):
        return PresentationDecision(
            kind=PresentationKind.SCATTER,
            fallback_kind=PresentationKind.TABLE,
            reason_code="correlation_roles_verified",
            include_exact_table=True,
            visualization=VisualizationKind.SCATTER,
        )
    if shape.semantic_shape is SemanticShape.CATEGORICAL_MATRIX and _supports_heatmap(shape):
        return PresentationDecision(
            kind=PresentationKind.HEATMAP,
            fallback_kind=PresentationKind.TABLE,
            reason_code="matrix_roles_verified",
            include_exact_table=True,
            visualization=VisualizationKind.HEATMAP,
        )

    if intent is PresentationIntent.THRESHOLD and _supports_threshold(shape):
        return _decision(PresentationKind.THRESHOLD_TABLE, "threshold_roles_verified")
    if intent is PresentationIntent.COMPARISON and _supports_comparison(shape):
        return PresentationDecision(
            kind=PresentationKind.COMPARISON,
            fallback_kind=PresentationKind.TABLE,
            reason_code="comparison_roles_verified",
            include_exact_table=True,
            visualization=VisualizationKind.COMPARISON_BAR,
        )
    if intent is PresentationIntent.TREND and _supports_time_series(shape):
        return PresentationDecision(
            kind=PresentationKind.TIME_SERIES,
            fallback_kind=PresentationKind.TABLE,
            reason_code="ordered_metric_series_verified",
            include_exact_table=True,
            visualization=(
                VisualizationKind.AREA
                if shape.semantic_shape is SemanticShape.CUMULATIVE_SERIES
                and _supports_cumulative_series(shape)
                else VisualizationKind.LINE
            ),
        )
    if intent is PresentationIntent.CHRONOLOGY and _supports_timeline(shape):
        return PresentationDecision(
            kind=PresentationKind.TIMELINE,
            fallback_kind=PresentationKind.TIMELINE,
            reason_code="ordered_timeline_verified",
            visualization=VisualizationKind.TRACKER,
        )
    if intent is PresentationIntent.COVERAGE and _supports_coverage(shape):
        return PresentationDecision(
            kind=PresentationKind.COVERAGE,
            fallback_kind=PresentationKind.TABLE,
            reason_code="coverage_denominator_verified",
            include_exact_table=True,
            visualization=VisualizationKind.CATEGORY_BAR,
        )
    if intent is PresentationIntent.DISTRIBUTION and _supports_bar(shape):
        return PresentationDecision(
            kind=PresentationKind.BAR,
            fallback_kind=PresentationKind.TABLE,
            reason_code="categorical_values_verified",
            include_exact_table=True,
            visualization=_distribution_visualization(shape),
        )
    if intent is PresentationIntent.SUMMARY and _supports_summary(shape):
        return _decision(PresentationKind.SUMMARY, "bounded_scalar_summary")
    if intent in {PresentationIntent.EXACT, PresentationIntent.AUDIT}:
        return _decision(PresentationKind.TABLE, "exact_values_required")
    if len(shape.records) <= 8 and (shape.heterogeneous or len(shape.columns) <= 2):
        return _decision(PresentationKind.LIST, "few_heterogeneous_records")
    return _decision(PresentationKind.TABLE, "row_comparison_required")


def _supports_threshold(shape: EvidenceShape) -> bool:
    return bool(
        shape.threshold_field
        and shape.current_field
        and shape.status_field
        and _fields_are_numeric(shape, shape.threshold_field, shape.current_field)
        and _has_one_unit(shape)
    )


def _supports_comparison(shape: EvidenceShape) -> bool:
    fields = tuple(
        field
        for field in (shape.baseline_field, shape.current_field, shape.target_field)
        if field is not None
    )
    return len(fields) >= 2 and _fields_are_numeric(shape, *fields) and _has_one_unit(shape)


def _supports_time_series(shape: EvidenceShape) -> bool:
    value_field = shape.current_field
    return bool(
        len(shape.records) >= 3
        and shape.timestamp_field
        and shape.metric_field
        and value_field
        and value_field in shape.numeric_fields
        and shape.timestamps_ordered
        and _one_string_value(shape.records, shape.metric_field)
        and _has_one_unit(shape)
    )


def _supports_cumulative_series(shape: EvidenceShape) -> bool:
    value_field = shape.current_field
    if not value_field or value_field not in shape.numeric_fields:
        return False
    values = [_numeric_value(record, value_field) for record in shape.records]
    return values == sorted(values)


def _supports_timeline(shape: EvidenceShape) -> bool:
    label_field = _first_field(list(shape.columns), ("event", "activity", "label", "status"))
    return bool(
        len(shape.records) >= 2
        and shape.timestamp_field
        and shape.timestamps_ordered
        and label_field
        and _all_non_empty_strings(shape.records, label_field)
    )


def _supports_coverage(shape: EvidenceShape) -> bool:
    if not shape.numerator_field or not shape.denominator_field:
        return False
    if not _fields_are_numeric(shape, shape.numerator_field, shape.denominator_field):
        return False
    return all(
        _numeric_value(record, shape.denominator_field) > 0
        and 0
        <= _numeric_value(record, shape.numerator_field)
        <= _numeric_value(record, shape.denominator_field)
        for record in shape.records
    )


def _supports_bar(shape: EvidenceShape) -> bool:
    value_field = shape.current_field
    return bool(
        2 <= len(shape.records) <= 12
        and shape.category_field
        and value_field
        and value_field in shape.numeric_fields
        and len(_string_values(shape.records, shape.category_field)) == len(shape.records)
        and _has_one_unit(shape)
    )


def _supports_summary(shape: EvidenceShape) -> bool:
    return len(shape.records) == 1 and 2 <= len(shape.columns) <= 8


def _supports_scatter(shape: EvidenceShape) -> bool:
    fields = _semantic_field_map(shape)
    label_field = fields.get("label")
    x_field = fields.get("x")
    y_field = fields.get("y")
    return bool(
        2 <= len(shape.records) <= _MAX_ANALYZED_ROWS
        and label_field
        and label_field in shape.columns
        and x_field
        and y_field
        and _fields_are_numeric(shape, x_field, y_field)
        and _all_non_empty_strings(shape.records, label_field)
    )


def _supports_heatmap(shape: EvidenceShape) -> bool:
    fields = _semantic_field_map(shape)
    row_field = fields.get("row")
    column_field = fields.get("column")
    value_field = fields.get("value")
    return bool(
        2 <= len(shape.records) <= _MAX_ANALYZED_ROWS
        and row_field in shape.columns
        and column_field in shape.columns
        and value_field
        and value_field in shape.numeric_fields
        and _all_non_empty_strings(shape.records, row_field, column_field)
        and len({(record[row_field], record[column_field]) for record in shape.records})
        == len(shape.records)
    )


def _distribution_visualization(shape: EvidenceShape) -> VisualizationKind:
    if shape.semantic_shape is SemanticShape.PART_TO_WHOLE and _supports_part_to_whole(shape):
        return VisualizationKind.DONUT
    if shape.semantic_shape is SemanticShape.RANKING and _supports_ranking(shape):
        return VisualizationKind.BAR_LIST
    return VisualizationKind.BAR


def _supports_part_to_whole(shape: EvidenceShape) -> bool:
    value_field = shape.current_field
    total_field = shape.denominator_field
    if (
        not value_field
        or not total_field
        or not _fields_are_numeric(shape, value_field, total_field)
    ):
        return False
    totals = {_numeric_value(record, total_field) for record in shape.records}
    if len(totals) != 1:
        return False
    total = next(iter(totals))
    values = [_numeric_value(record, value_field) for record in shape.records]
    return (
        total > 0
        and all(value >= 0 for value in values)
        and math.isclose(
            sum(values),
            total,
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
    )


def _supports_ranking(shape: EvidenceShape) -> bool:
    rank_field = next(
        (field for field in shape.columns if field.rsplit(".", 1)[-1].casefold() == "rank"),
        None,
    )
    if not rank_field or rank_field not in shape.numeric_fields:
        return False
    ranks = [_numeric_value(record, rank_field) for record in shape.records]
    return all(rank > 0 for rank in ranks) and ranks == sorted(set(ranks))


def _semantic_field_map(shape: EvidenceShape) -> dict[str, str]:
    return dict(shape.semantic_fields)


def _fallback_for_records(shape: EvidenceShape, reason_code: str) -> PresentationDecision:
    kind = PresentationKind.LIST if len(shape.records) <= 4 else PresentationKind.TABLE
    return _decision(kind, reason_code)


def _decision(kind: PresentationKind, reason_code: str) -> PresentationDecision:
    return PresentationDecision(kind=kind, fallback_kind=kind, reason_code=reason_code)


def _fields_are_numeric(shape: EvidenceShape, *fields: str) -> bool:
    return all(field in shape.numeric_fields for field in fields)


def _has_one_unit(shape: EvidenceShape) -> bool:
    return shape.unit_field is not None and len(shape.units) == 1


def _one_string_value(records: tuple[Mapping[str, object], ...], field: str) -> bool:
    return len(_string_values(records, field)) == 1


def _string_values(
    records: list[Mapping[str, object]] | tuple[Mapping[str, object], ...],
    field: str | None,
) -> tuple[str, ...]:
    if field is None:
        return ()
    values = {
        value.strip()
        for record in records
        if isinstance((value := record.get(field)), str) and value.strip()
    }
    return tuple(sorted(values))


def _all_non_empty_strings(
    records: tuple[Mapping[str, object], ...],
    *fields: str,
) -> bool:
    return all(
        isinstance(value := record.get(field), str) and bool(value.strip())
        for record in records
        for field in fields
    )


def _timestamps_are_ordered(
    records: list[Mapping[str, object]],
    field: str | None,
) -> bool:
    if field is None:
        return False
    timestamps: list[datetime] = []
    for record in records:
        raw = record.get(field)
        if not isinstance(raw, str) or _RFC3339.fullmatch(raw) is None:
            return False
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return False
        if parsed.tzinfo is None:
            return False
        timestamps.append(parsed)
    return timestamps == sorted(set(timestamps))


def _limitations(output: Mapping[str, object]) -> tuple[str, ...]:
    raw = output.get("limitations", ())
    if not isinstance(raw, list | tuple):
        return ()
    return tuple(item for item in raw if isinstance(item, str) and item)


def _first_field(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    by_leaf = {field.rsplit(".", 1)[-1].casefold(): field for field in columns}
    return next((by_leaf[candidate] for candidate in candidates if candidate in by_leaf), None)


def _is_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_finite_number(value: object) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(float(value))


def _numeric_value(record: Mapping[str, object], field: str) -> float:
    value = record[field]
    if not _is_finite_number(value):  # pragma: no cover - guarded by _fields_are_numeric
        raise ValueError("presentation evidence numeric field is invalid")
    return float(cast(Real, value))


__all__ = [
    "EvidenceShape",
    "PresentationDecision",
    "PresentationIntent",
    "PresentationKind",
    "SemanticShape",
    "VisualizationKind",
    "analyze_evidence_shape",
    "plan_presentation",
]
