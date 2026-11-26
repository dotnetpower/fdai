"""HTML format encoder - a standalone HTML fragment per report.

Renders each widget in a ``<section>`` with the widget id / title, plus
a shallow-typed body: table widgets become an actual ``<table>``,
scalar widgets become a ``<strong>`` value, everything else becomes a
``<pre>`` block with the pretty-printed JSON. Table cells are HTML-escaped.

The output is a fragment (no ``<html>`` / ``<body>`` wrapper) so a
caller can embed it in whatever shell they like. Content-Type is set to
``text/html; charset=utf-8``.
"""

from __future__ import annotations

import html
import json
from collections.abc import Mapping
from typing import Any

from fdai.core.reporting.models import RenderedReport, RenderedWidget


class HtmlFormatEncoder:
    """Serialize a :class:`RenderedReport` to a UTF-8 HTML fragment."""

    name = "html"
    content_type = "text/html; charset=utf-8"

    def encode(self, report: RenderedReport) -> bytes:
        lines: list[str] = [
            "<article class='fdai-report'>",
            f"<header><h1>{html.escape(report.name)}</h1>",
        ]
        if report.description:
            lines.append(f"<p>{html.escape(report.description)}</p>")
        lines.append(
            "<ul class='fdai-meta'>"
            f"<li>report_id: <code>{html.escape(report.id)}</code></li>"
            f"<li>version: <code>{html.escape(report.version)}</code></li>"
            f"<li>generated_at: <code>{html.escape(report.generated_at.isoformat())}</code></li>"
            f"<li>window: <code>{html.escape(report.time_range[0].isoformat())}</code>"
            f" .. <code>{html.escape(report.time_range[1].isoformat())}</code></li>"
            "</ul></header>"
        )
        for widget in report.widgets:
            lines.extend(_render_widget(widget))
        lines.append("</article>")
        return "\n".join(lines).encode("utf-8")


def _render_widget(widget: RenderedWidget) -> list[str]:
    lines: list[str] = [
        f"<section class='fdai-widget' data-type='{html.escape(widget.type)}' "
        f"data-id='{html.escape(widget.id)}'>",
        f"<h2>{html.escape(widget.title)}</h2>",
    ]
    if widget.error is not None:
        lines.append(f"<div class='fdai-error'>{html.escape(widget.error)}</div>")
        lines.append("</section>")
        return lines
    if widget.type == "query_value":
        value = widget.data.get("value")
        lines.append(f"<strong>{html.escape(str(value))}</strong>")
    elif widget.type in ("table", "top_list"):
        lines.extend(_render_table(widget.data))
    elif widget.type == "free_text":
        # `body` is intentionally rendered pre-escaped as text -
        # a report YAML author can put markdown in there, but this
        # encoder is a defensive-first renderer, not a markdown parser.
        lines.append(f"<pre>{html.escape(str(widget.data.get('body', '')))}</pre>")
    elif widget.type in ("group", "tabs"):
        for child in widget.children:
            lines.extend(_render_widget(child))
    else:
        lines.append(
            "<pre>"
            + html.escape(json.dumps(dict(widget.data), indent=2, ensure_ascii=False))
            + "</pre>"
        )
    lines.append("</section>")
    return lines


def _render_table(data: Mapping[str, Any]) -> list[str]:
    columns = data.get("columns") or []
    rows = data.get("rows") or []
    if not columns:
        return [
            "<pre>" + html.escape(json.dumps(dict(data), indent=2, ensure_ascii=False)) + "</pre>"
        ]
    out: list[str] = ["<table>", "<thead><tr>"]
    for col in columns:
        out.append(f"<th>{html.escape(str(col))}</th>")
    out.append("</tr></thead><tbody>")
    for row in rows:
        if not isinstance(row, Mapping):
            # Non-Mapping row from a bad datasource: emit blanks so we
            # never crash the whole table on one hostile record.
            out.append("<tr>" + "".join("<td></td>" for _ in columns) + "</tr>")
            continue
        out.append("<tr>")
        for col in columns:
            value = row.get(col)
            out.append(f"<td>{html.escape('' if value is None else str(value))}</td>")
        out.append("</tr>")
    out.append("</tbody></table>")
    return out


__all__ = ["HtmlFormatEncoder"]
