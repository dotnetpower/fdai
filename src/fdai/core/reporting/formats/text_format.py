"""Plain-text format encoder - a stdout-friendly summary.

Ideal for `curl … | less`, e-mail bodies, and CLI dashboards. No
markdown syntax, no ANSI codes, ASCII punctuation only.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.reporting.models import RenderedReport, RenderedWidget


class TextFormatEncoder:
    """Serialize a :class:`RenderedReport` to plain UTF-8 text."""

    name = "text"
    content_type = "text/plain; charset=utf-8"

    def encode(self, report: RenderedReport) -> bytes:
        lines: list[str] = [
            f"# {report.name}",
            f"id: {report.id}  version: {report.version}",
            f"generated_at: {report.generated_at.isoformat()}",
            (f"window: {report.time_range[0].isoformat()} .. {report.time_range[1].isoformat()}"),
        ]
        if report.variables:
            lines.append("variables: " + ", ".join(f"{k}={v}" for k, v in report.variables.items()))
        lines.append("")
        for widget in report.widgets:
            lines.extend(_render_widget(widget, level=1))
            lines.append("")
        return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def _render_widget(widget: RenderedWidget, *, level: int) -> list[str]:
    indent = "  " * max(0, level - 1)
    heading_prefix = "=" if level == 1 else "-"
    header = f"{indent}{heading_prefix * (2 if level == 1 else 1)} {widget.title}"
    lines = [header]
    if widget.error is not None:
        lines.append(f"{indent}  ERROR: {widget.error}")
        return lines
    if widget.type == "query_value":
        lines.append(f"{indent}  value: {widget.data.get('value')}")
    elif widget.type in ("table", "top_list"):
        lines.extend(_render_table(widget.data, indent=indent))
    elif widget.type == "free_text":
        for body_line in str(widget.data.get("body", "")).splitlines():
            lines.append(f"{indent}  {body_line}")
    elif widget.type in ("group", "tabs"):
        for child in widget.children:
            lines.extend(_render_widget(child, level=level + 1))
    else:
        # Compact representation - the FE contract is elsewhere.
        summary_key = next(iter(widget.data), None)
        lines.append(
            f"{indent}  ({widget.type}: {summary_key}={widget.data.get(summary_key)})"
            if summary_key
            else f"{indent}  ({widget.type}: {widget.data})"
        )
    return lines


def _render_table(data: Mapping[str, Any], *, indent: str) -> list[str]:
    columns = data.get("columns") or []
    rows = data.get("rows") or []
    if not columns:
        return [f"{indent}  {data}"]
    out = [f"{indent}  {' | '.join(str(c) for c in columns)}"]
    for row in rows[:50]:
        cells = ["" if row.get(c) is None else str(row.get(c)) for c in columns]
        out.append(f"{indent}  {' | '.join(cells)}")
    if len(rows) > 50:
        out.append(f"{indent}  ... ({len(rows) - 50} more rows)")
    return out


__all__ = ["TextFormatEncoder"]
