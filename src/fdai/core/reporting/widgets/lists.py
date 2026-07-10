"""List-family widget builders: table, top_list, list_stream.

Each builder produces a payload the FE renders as a scrollable list or
table. Every list is bounded (``options.limit``, clamped to a hard
ceiling) so a runaway datasource cannot serve a million-row body to the
console.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from fdai.core.reporting.models import DataSet, WidgetSpec

_HARD_ROW_CEILING = 1000
"""Absolute upper bound on rows any list widget may return.

Read-only surface; a large list is a rendering problem, not a
data-preservation problem. A caller who needs more rows uses CSV export
(the CSV encoder ignores this ceiling).
"""


class TableBuilder:
    """Render :attr:`DataSet.rows` as an ordered-column table."""

    type_name = "table"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        limit = _clamp_limit(spec.options.get("limit"))
        columns = data.columns or _derive_columns(data.rows)
        rows = [{col: row.get(col) for col in columns} for row in list(data.rows)[:limit]]
        return {
            "columns": list(columns),
            "rows": rows,
            "total_rows": len(data.rows),
        }


class TopListBuilder:
    """Render the top-N rows by a ranking column.

    ``options.rank_by`` names the column to sort by (defaults to
    ``"value"``); ``options.order`` is ``"desc"`` (default) or ``"asc"``;
    ``options.limit`` caps the row count (default 10, hard ceiling
    :data:`_HARD_ROW_CEILING`). Rows missing the rank column are dropped
    to keep the ranking honest.
    """

    type_name = "top_list"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        rank_by = str(spec.options.get("rank_by", "value"))
        order = str(spec.options.get("order", "desc")).lower()
        limit = _clamp_limit(spec.options.get("limit", 10))
        ranked = [row for row in data.rows if rank_by in row]
        ranked.sort(
            key=lambda row: _numeric(row.get(rank_by)),
            reverse=(order == "desc"),
        )
        top = ranked[:limit]
        columns = data.columns or _derive_columns(top)
        return {
            "columns": list(columns),
            "rows": [{col: row.get(col) for col in columns} for row in top],
            "ranked_by": rank_by,
            "order": "desc" if order == "desc" else "asc",
            "total_rows": len(data.rows),
        }


class ListStreamBuilder:
    """Render :attr:`DataSet.rows` as a newest-first event / log stream.

    Rows keep their full payload (no column projection) so the FE can
    show a per-row detail drawer. ``options.timestamp_field`` names the
    column used for the "newest first" sort (defaults to ``"at"``).
    """

    type_name = "list_stream"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        timestamp_field = str(spec.options.get("timestamp_field", "at"))
        limit = _clamp_limit(spec.options.get("limit", 50))
        ordered = sorted(
            data.rows,
            key=lambda row: _timestamp_sort_key(row.get(timestamp_field, "")),
            reverse=True,
        )
        return {
            "items": [dict(row) for row in ordered[:limit]],
            "total_rows": len(data.rows),
        }


def _clamp_limit(raw: Any) -> int:
    try:
        value = int(raw) if raw is not None else _HARD_ROW_CEILING
    except (TypeError, ValueError):
        value = _HARD_ROW_CEILING
    if value < 1:
        return 1
    if value > _HARD_ROW_CEILING:
        return _HARD_ROW_CEILING
    return value


def _derive_columns(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for row in rows:
        for key in row:
            seen[key] = None
    return tuple(seen)


def _numeric(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        # Non-finite (NaN/Inf) as a sort key scrambles ordering because
        # every NaN comparison is False; push it to the tail instead.
        return float(value) if math.isfinite(value) else float("-inf")
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float("-inf")
    return result if math.isfinite(result) else float("-inf")


def _timestamp_sort_key(value: Any) -> tuple[int, float, str]:
    """Order-stable sort key for a timestamp cell.

    A numeric (epoch) timestamp sorts numerically - ``str()`` would order
    ``9`` after ``100`` - while an ISO-8601 / textual timestamp sorts
    lexicographically (which is chronological for ISO-8601). Mixed types
    are grouped deterministically rather than raising.
    """
    if isinstance(value, bool):
        return (1, 0.0, str(value))
    if isinstance(value, (int, float)) and math.isfinite(value):
        return (0, float(value), "")
    return (1, 0.0, str(value))


class EventStreamBuilder:
    """Severity-tagged event stream.

    Same shape as :class:`ListStreamBuilder` plus a
    ``counts_by_severity`` roll-up (``critical`` / ``high`` / ``medium``
    / ``low`` / ``info``) so a FE can render both the feed and a
    summary chip.
    """

    type_name = "event_stream"

    _SEVERITIES: tuple[str, ...] = ("critical", "high", "medium", "low", "info")

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        timestamp_field = str(spec.options.get("timestamp_field", "at"))
        severity_field = str(spec.options.get("severity_field", "severity"))
        limit = _clamp_limit(spec.options.get("limit", 50))
        ordered = sorted(
            data.rows,
            key=lambda row: _timestamp_sort_key(row.get(timestamp_field, "")),
            reverse=True,
        )
        counts = dict.fromkeys(self._SEVERITIES, 0)
        for row in data.rows:
            severity = str(row.get(severity_field, "info")).lower()
            if severity not in counts:
                severity = "info"
            counts[severity] += 1
        return {
            "items": [dict(row) for row in ordered[:limit]],
            "counts_by_severity": counts,
            "total_rows": len(data.rows),
        }


__all__ = [
    "EventStreamBuilder",
    "ListStreamBuilder",
    "TableBuilder",
    "TopListBuilder",
]
