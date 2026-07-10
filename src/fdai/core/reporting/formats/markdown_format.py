"""Markdown format encoder - notebook-style narrative render.

Turns a :class:`RenderedReport` into a heading + section layout suitable
for GitHub / a wiki / a Datadog-style Notebook. Only a subset of widget
types renders with a rich body; the rest fall back to a compact
``json`` code block so the output stays lossless.

Rendering rules:

- Report title / description / time range at the top.
- One ``##`` per widget with the title.
- ``query_value`` -> a bold value.
- ``table`` / ``top_list`` -> a markdown table.
- ``free_text`` / ``note`` -> the body inline (with severity for note).
- ``timeseries`` / ``heatmap`` -> a one-line summary + fenced JSON of
  the series (chart rendering is delegated to whoever renders the
  markdown).
- everything else -> fenced JSON of the widget ``data`` mapping.

Every line is ASCII-punctuation only per language policy.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from fdai.core.reporting.models import RenderedReport, RenderedWidget


class MarkdownFormatEncoder:
    """Serialize a :class:`RenderedReport` to a UTF-8 markdown body."""

    name = "markdown"
    content_type = "text/markdown; charset=utf-8"

    def encode(self, report: RenderedReport) -> bytes:
        lines: list[str] = []
        lines.append(f"# {report.name}")
        lines.append("")
        if report.description:
            lines.append(report.description)
            lines.append("")
        lines.append(f"- report_id: `{report.id}` (v{report.version})")
        lines.append(f"- generated_at: `{report.generated_at.isoformat()}`")
        lines.append(
            f"- window: `{report.time_range[0].isoformat()}` .. "
            f"`{report.time_range[1].isoformat()}`"
        )
        if report.variables:
            var_bits = ", ".join(f"{k}={v}" for k, v in report.variables.items())
            lines.append(f"- variables: `{var_bits}`")
        if report.tags:
            lines.append(f"- tags: {', '.join(f'`{t}`' for t in report.tags)}")
        lines.append("")
        for widget in report.widgets:
            lines.extend(_render_widget(widget, level=2))
            lines.append("")
        return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def _render_widget(widget: RenderedWidget, *, level: int) -> list[str]:
    lines: list[str] = []
    header_prefix = "#" * max(1, min(level, 6))
    lines.append(f"{header_prefix} {widget.title}")
    lines.append("")
    if widget.error is not None:
        lines.append(f"> ERROR: {widget.error}")
        return lines

    if widget.type == "free_text":
        lines.append(str(widget.data.get("body", "")))
        return lines

    if widget.type == "note":
        severity = widget.data.get("severity", "info")
        lines.append(f"> ({severity}) {widget.data.get('body', '')}")
        return lines

    if widget.type == "query_value":
        value = widget.data.get("value")
        unit = widget.data.get("unit")
        rendered = f"**{value}**" if unit is None else f"**{value} {unit}**"
        lines.append(rendered)
        return lines

    if widget.type in ("table", "top_list"):
        lines.extend(_render_table(widget.data))
        return lines

    if widget.type == "group":
        for child in widget.children:
            lines.extend(_render_widget(child, level=level + 1))
            lines.append("")
        return lines

    lines.append("```json")
    lines.append(json.dumps(dict(widget.data), indent=2, ensure_ascii=False))
    lines.append("```")
    return lines


def _render_table(data: Mapping[str, Any]) -> list[str]:
    columns = data.get("columns") or []
    rows = data.get("rows") or []
    if not columns:
        return [
            "```json",
            json.dumps(dict(data), indent=2, ensure_ascii=False),
            "```",
        ]
    lines: list[str] = []
    lines.append("| " + " | ".join(_escape(c) for c in columns) + " |")
    lines.append("|" + "|".join(" --- " for _ in columns) + "|")
    row_iter: Sequence[Mapping[str, Any]] = rows
    for row in row_iter:
        cells = [_escape(row.get(c)) for c in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


__all__ = ["MarkdownFormatEncoder"]
