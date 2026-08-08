"""CSV format encoder - flattens every table-shaped widget into one CSV.

The output is one CSV **per report**. Each table-shaped widget's rows
are concatenated with a leading ``widget_id`` / ``widget_title`` /
``widget_type`` column so a spreadsheet consumer can slice by widget.
Widgets that do not carry rows (query_value / free_text / group / ...)
emit one row with the flattened ``data`` as a JSON blob so nothing is
silently dropped.

The header row is the union of every column across the touched
widgets - stable across renders because column order is derived from
first appearance.

Formula-injection safe: any cell whose first character is a spreadsheet
formula trigger (``=`` / ``+`` / ``-`` / ``@`` / TAB / CR) is prefixed
with a single quote per OWASP guidance so opening the CSV in Excel /
LibreOffice / Google Sheets renders the value as text, not a formula.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping, Sequence
from typing import Any

from fdai.core.reporting.models import RenderedReport, RenderedWidget

_TABLE_WIDGET_TYPES: frozenset[str] = frozenset({"table", "top_list"})
_LEADING_COLUMNS: tuple[str, ...] = (
    "widget_id",
    "widget_title",
    "widget_type",
)
# OWASP "CSV / formula injection" trigger characters. Any cell that
# starts with one is prefixed with `'` so a spreadsheet renders it as
# text. Includes TAB and CR because Excel interprets leading whitespace
# followed by a formula trigger as a formula.
_FORMULA_TRIGGERS: frozenset[str] = frozenset({"=", "+", "-", "@", "\t", "\r"})


class CsvFormatEncoder:
    """Serialize a :class:`RenderedReport` to a UTF-8 CSV body."""

    name = "csv"
    content_type = "text/csv; charset=utf-8"

    def encode(self, report: RenderedReport) -> bytes:
        widgets = list(_iter_widgets(report.widgets))
        columns = self._collect_columns(widgets)
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for widget in widgets:
            for row in self._widget_rows(widget):
                writer.writerow(row)
        return buffer.getvalue().encode("utf-8")

    @staticmethod
    def _collect_columns(widgets: Sequence[RenderedWidget]) -> tuple[str, ...]:
        seen: dict[str, None] = {name: None for name in _LEADING_COLUMNS}
        for widget in widgets:
            if widget.type in _TABLE_WIDGET_TYPES:
                for col in widget.data.get("columns") or ():
                    seen[str(col)] = None
            else:
                seen["value"] = None
        return tuple(seen)

    @staticmethod
    def _widget_rows(widget: RenderedWidget) -> list[dict[str, Any]]:
        leading: dict[str, Any] = {
            "widget_id": widget.id,
            "widget_title": widget.title,
            "widget_type": widget.type,
        }
        if widget.type in _TABLE_WIDGET_TYPES:
            columns = widget.data.get("columns") or ()
            out: list[dict[str, Any]] = []
            for row in widget.data.get("rows") or ():
                # Defense-in-depth: a fork-authored datasource that
                # returned a non-Mapping row (a bare string, an int,
                # ...) would otherwise crash the whole encoder.
                if not isinstance(row, Mapping):
                    continue
                merged: dict[str, Any] = dict(leading)
                for col in columns:
                    merged[str(col)] = _stringify(row.get(col))
                out.append(merged)
            if not out:
                return [dict(leading)]
            return out
        return [
            {
                **leading,
                "value": _stringify(_shallow_summary(widget.data)),
            }
        ]


def _iter_widgets(widgets: Sequence[RenderedWidget]) -> list[RenderedWidget]:
    ordered: list[RenderedWidget] = []
    for widget in widgets:
        ordered.append(widget)
        if widget.children:
            ordered.extend(_iter_widgets(widget.children))
    return ordered


def _shallow_summary(data: Mapping[str, Any]) -> Any:
    if "value" in data:
        return data["value"]
    return json.dumps(dict(data), ensure_ascii=False)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float, bool, str)):
        rendered = str(value)
    else:
        rendered = json.dumps(value, ensure_ascii=False)
    return _sanitize_cell(rendered)


def _sanitize_cell(text: str) -> str:
    """Neutralize spreadsheet formula-injection triggers.

    Any cell whose first character is one of :data:`_FORMULA_TRIGGERS`
    is prefixed with a single quote. Spreadsheet apps render such a
    cell as text and hide the quote in the UI while keeping it in the
    stored value.
    """
    if not text:
        return text
    if text[0] in _FORMULA_TRIGGERS:
        return "'" + text
    return text


__all__ = ["CsvFormatEncoder"]
