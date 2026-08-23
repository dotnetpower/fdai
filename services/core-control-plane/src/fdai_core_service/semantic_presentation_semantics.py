"""Project renderer-neutral presentation semantics from verified query rows."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import cast

_TEMPORAL_OUTPUTS = frozenset({"target_resource_metric_series", "temporal_comparison"})
_CHRONOLOGY_OUTPUTS = frozenset(
    {"resource_event_history", "subscription_service_health", "topology_graph"}
)
_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


def project_presentation_semantics(
    *,
    operation: str,
    output_shape: str,
    outputs: Sequence[Mapping[str, object]],
) -> dict[str, object] | None:
    """Return a proven semantic shape or omit metadata when field roles are ambiguous."""
    rows = _single_output_rows(outputs)
    if not rows:
        return None
    fields = set.intersection(*(set(row) for row in rows))

    if output_shape == "temporal_comparison" and _role_comparison(rows, fields):
        return {"shape": "role_comparison", "fields": {}}
    if (
        output_shape in _TEMPORAL_OUTPUTS
        and _has(fields, "timestamp", "metric", "unit")
        and _timestamps_are_ordered(rows, "timestamp")
    ):
        if "cumulative_value" in fields and _non_decreasing_field(rows, "cumulative_value"):
            return {"shape": "cumulative_series", "fields": {}}
        if "value" in fields and _finite_field(rows, "value"):
            return {"shape": "temporal_series", "fields": {}}
    if output_shape in _CHRONOLOGY_OUTPUTS and _chronology(rows, fields):
        return {"shape": "chronology", "fields": {}}
    if output_shape != "aggregation_table":
        return None
    if _has(fields, "category", "numerator", "denominator"):
        return {"shape": "coverage", "fields": {}}
    if (
        _has(fields, "row", "column", "value")
        and _finite_field(rows, "value")
        and _non_empty_string_field(rows, "row", "column")
        and _coordinates_are_unique(rows, "row", "column")
    ):
        return {
            "shape": "categorical_matrix",
            "fields": {"row": "row", "column": "column", "value": "value"},
        }
    if operation == "compare" and _has(fields, "label", "x", "y"):
        if _finite_field(rows, "x", "y") and _non_empty_string_field(rows, "label"):
            return {
                "shape": "correlation",
                "fields": {"label": "label", "x": "x", "y": "y"},
            }
    if (
        _has(fields, "rank", "category", "value", "unit")
        and _finite_field(rows, "rank", "value")
        and _one_string_value(rows, "unit")
    ):
        return {"shape": "ranking", "fields": {}}
    if _parts_form_one_whole(rows, fields):
        return {"shape": "part_to_whole", "fields": {}}
    if (
        _has(fields, "category", "value", "unit")
        and _finite_field(rows, "value")
        and _one_string_value(rows, "unit")
    ):
        return {"shape": "categorical_comparison", "fields": {}}
    return None


def _single_output_rows(
    outputs: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    if len(outputs) != 1:
        return ()
    raw_rows = outputs[0].get("rows")
    if not isinstance(raw_rows, list) or not raw_rows:
        return ()
    rows: list[Mapping[str, object]] = []
    for raw_row in raw_rows:
        values = raw_row.get("values") if isinstance(raw_row, Mapping) else None
        if not isinstance(values, Mapping) or not values:
            return ()
        rows.append(values)
    return tuple(rows)


def _has(fields: set[str], *required: str) -> bool:
    return set(required).issubset(fields)


def _finite_field(rows: Sequence[Mapping[str, object]], *fields: str) -> bool:
    return all(_finite(row.get(field)) for row in rows for field in fields)


def _finite(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _non_decreasing_field(rows: Sequence[Mapping[str, object]], field: str) -> bool:
    if not _finite_field(rows, field):
        return False
    values = [_numeric_value(row[field]) for row in rows]
    return values == sorted(values)


def _non_empty_string_field(rows: Sequence[Mapping[str, object]], *fields: str) -> bool:
    return all(
        isinstance(value := row.get(field), str) and bool(value.strip())
        for row in rows
        for field in fields
    )


def _coordinates_are_unique(
    rows: Sequence[Mapping[str, object]],
    row_field: str,
    column_field: str,
) -> bool:
    coordinates = {(row[row_field], row[column_field]) for row in rows}
    return len(coordinates) == len(rows)


def _role_comparison(rows: Sequence[Mapping[str, object]], fields: set[str]) -> bool:
    role_fields = tuple(field for field in ("baseline", "current", "target") if field in fields)
    return len(rows) == 1 and len(role_fields) >= 2 and _finite_field(rows, *role_fields)


def _chronology(rows: Sequence[Mapping[str, object]], fields: set[str]) -> bool:
    return (
        "timestamp" in fields
        and bool(fields & {"event", "activity", "label", "status"})
        and _timestamps_are_ordered(rows, "timestamp")
    )


def _timestamps_are_ordered(rows: Sequence[Mapping[str, object]], field: str) -> bool:
    timestamps: list[datetime] = []
    for row in rows:
        raw = row.get(field)
        if not isinstance(raw, str) or _RFC3339.fullmatch(raw) is None:
            return False
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return False
        timestamps.append(parsed)
    return timestamps == sorted(set(timestamps))


def _parts_form_one_whole(rows: Sequence[Mapping[str, object]], fields: set[str]) -> bool:
    if (
        not _has(fields, "category", "value", "total", "unit")
        or not _finite_field(rows, "value", "total")
        or not _one_string_value(rows, "unit")
    ):
        return False
    totals = {_numeric_value(row["total"]) for row in rows}
    if len(totals) != 1:
        return False
    total = next(iter(totals))
    return total > 0 and math.isclose(
        sum(_numeric_value(row["value"]) for row in rows),
        total,
        rel_tol=1e-9,
        abs_tol=1e-9,
    )


def _one_string_value(rows: Sequence[Mapping[str, object]], field: str) -> bool:
    values = {row.get(field) for row in rows}
    return len(values) == 1 and all(isinstance(value, str) and value for value in values)


def _numeric_value(value: object) -> float:
    if not _finite(value):  # pragma: no cover - callers validate complete fields first
        raise ValueError("presentation semantic value MUST be finite")
    return float(cast(int | float, value))


__all__ = ["project_presentation_semantics"]
