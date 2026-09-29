"""Show verified query output rows as a bounded evidence table, never as authored prose.

A verified result without a reviewed presentation used to show only its row count, so a
compiled count or relation read hid its answer in technical details. The table displays the
verified values exactly, states how many rows it does not show, and adds no fact of its own.
"""

from __future__ import annotations

from collections.abc import Mapping

_MAX_ROWS = 20
_MAX_COLUMNS = 6
_MAX_CELL_CHARS = 120
_MAX_TABLE_CHARS = 4_000
# Display order for common verified fields; every other field follows in first-seen order.
_LEADING_FIELDS = ("name", "type", "status", "location", "operation", "value", "group")
# The identity and ObjectType of a named row stay in technical details, where they are exact.
_DETAIL_FIELDS = frozenset({"id", "object_type"})


def verified_rows_table(output: Mapping[str, object], *, korean: bool) -> list[str]:
    """Return markdown table lines for one verified output, or nothing without rows."""

    rows = output.get("rows")
    values = [
        row["values"]
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, Mapping) and isinstance(row.get("values"), Mapping)
    ]
    if not values:
        return []
    seen: dict[str, None] = {}
    for item in values:
        for key in item:
            if isinstance(key, str):
                seen.setdefault(key, None)
    named = "name" in seen
    columns = [key for key in _LEADING_FIELDS if key in seen] + [
        key for key in seen if key not in _LEADING_FIELDS and not (named and key in _DETAIL_FIELDS)
    ]
    shown_columns = columns[:_MAX_COLUMNS]
    lines = ["", "| " + " | ".join(shown_columns) + " |", "|" + "---|" * len(shown_columns)]
    budget = _MAX_TABLE_CHARS - sum(len(line) for line in lines)
    shown_rows = 0
    for item in values[:_MAX_ROWS]:
        line = "| " + " | ".join(_bounded(_cell(item.get(key)), korean) for key in shown_columns)
        line += " |"
        if len(line) > budget:
            break
        lines.append(line)
        budget -= len(line)
        shown_rows += 1
    if shown_rows == 0:
        return []
    hidden_rows = len(values) - shown_rows
    hidden_columns = len(columns) - len(shown_columns)
    if hidden_rows > 0:
        lines.append(
            f"- 표에 표시하지 않은 검증된 행 {hidden_rows}개는 기술 상세에 있습니다."
            if korean
            else f"- {hidden_rows} more verified rows are in technical details."
        )
    if hidden_columns > 0:
        lines.append(
            f"- 표에 표시하지 않은 검증된 필드 {hidden_columns}개는 기술 상세에 있습니다."
            if korean
            else f"- {hidden_columns} more verified fields are in technical details."
        )
    return lines


def _bounded(cell: str, korean: bool) -> str:
    # A long value is named, not cut, so a shown cell never displays a partial value.
    if len(cell) <= _MAX_CELL_CHARS:
        return cell
    return "(기술 상세 참조)" if korean else "(see technical details)"


def _cell(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Mapping):
        return ", ".join(f"{key}={_scalar(item)}" for key, item in value.items()) or "-"
    if isinstance(value, list | tuple):
        return ", ".join(_scalar(item) for item in value) or "-"
    return _scalar(value)


def _scalar(value: object) -> str:
    text = "-" if value is None else str(value)
    # Table syntax characters are escaped so a verified value cannot change the table shape.
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


__all__ = ["verified_rows_table"]
