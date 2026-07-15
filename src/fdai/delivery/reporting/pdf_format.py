"""Print-quality PDF encoder for rendered FDAI reports.

The encoder lives in ``delivery`` because WeasyPrint is an optional rendering
runtime with native Cairo/Pango dependencies. ``core.reporting`` only knows the
``FormatEncoder`` Protocol and the inert ``RenderedReport`` value.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from html import escape
from importlib.resources import files
from typing import Any

from fdai.core.reporting.models import RenderedReport, RenderedWidget
from fdai.core.reporting.registry import FormatRegistry

PdfRenderer = Callable[[str, str], bytes]


class PdfRenderUnavailableError(RuntimeError):
    """Raised when the optional PDF runtime is unavailable or returns no bytes."""


class PdfFormatEncoder:
    """Encode a ``RenderedReport`` as an A4 evidence dossier."""

    name = "pdf"
    content_type = "application/pdf"

    def __init__(self, renderer: PdfRenderer | None = None) -> None:
        self._renderer = renderer or _render_with_weasyprint

    def encode(self, report: RenderedReport) -> bytes:
        html = render_report_html(report)
        css = _load_css()
        rendered = self._renderer(html, css)
        if not rendered:
            raise PdfRenderUnavailableError("PDF renderer returned an empty document")
        return rendered


def install_pdf_format(registry: FormatRegistry) -> FormatRegistry:
    """Register the opt-in PDF encoder on an existing format registry."""
    registry.register(PdfFormatEncoder())
    return registry


def install_pdf_format_if_available(registry: FormatRegistry) -> FormatRegistry:
    """Register PDF only when its optional native runtime imports cleanly."""
    try:
        from weasyprint import HTML  # noqa: F401
    except (ImportError, OSError):
        return registry
    return install_pdf_format(registry)


def render_report_html(report: RenderedReport) -> str:
    """Return the deterministic, escaped HTML document supplied to WeasyPrint."""
    canonical = json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":"))
    source_sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if report.id == "incident-rca-dossier":
        from fdai.delivery.reporting.rca_dossier import render_rca_dossier

        return render_rca_dossier(report, source_sha=source_sha)
    correlation_id = report.variables.get("correlation_id") or "not scoped"
    toc = "".join(
        f'<li><a href="#{_anchor(widget.id)}">{escape(widget.title)}</a></li>'
        for widget in report.widgets
    )
    sections = "".join(
        _render_widget(widget, index) for index, widget in enumerate(report.widgets, 1)
    )
    issue_count = sum(1 for widget in report.widgets if widget.error is not None)
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>{escape(report.name)}</title></head>
<body>
  <section class="cover">
    <div class="cover-band">
      <p class="kicker">FDAI operational evidence dossier</p>
      <h1>{escape(report.name)}</h1>
      <p class="subtitle">Incident and root-cause analysis report</p>
    </div>
    <dl class="cover-meta">
      <dt>Report id</dt><dd><code>{escape(report.id)} v{escape(report.version)}</code></dd>
      <dt>Correlation id</dt><dd><code>{escape(correlation_id)}</code></dd>
      <dt>Generated</dt><dd>{escape(report.generated_at.isoformat())}</dd>
            <dt>Evidence window</dt>
            <dd>{escape(report.time_range[0].isoformat())}<br>
                to {escape(report.time_range[1].isoformat())}</dd>
      <dt>Source SHA-256</dt><dd><code>{source_sha}</code></dd>
    </dl>
    <p class="classification">INTERNAL OPERATIONAL RECORD</p>
        <p class="cover-note">Read-only evidence projection. RCA findings are hypotheses,
            not execution verdicts. Missing evidence is shown as unavailable and is never
            inferred by the renderer.</p>
  </section>

  <section class="overview">
    <p class="chapter-kicker">Overview</p>
    <h1>At a Glance</h1>
    <div class="kpi-grid">
      {_kpi("Report sections", len(report.widgets))}
      {_kpi("Render issues", issue_count)}
      {_kpi("Evidence tags", len(report.tags))}
    </div>
    <div class="summary-block">
      <h2>Purpose</h2>
      <p>{escape(report.description)}</p>
    </div>
    <div class="summary-block">
      <h2>Document control</h2>
            <p>This document is a deterministic rendering of the server-owned report envelope.
                The SHA-256 on the cover identifies that envelope for replay and comparison.</p>
    </div>
  </section>

  <nav class="toc">
    <p class="chapter-kicker">Contents</p>
    <h1>Table of Contents</h1>
    <ol>{toc}</ol>
  </nav>

  <main>{sections}</main>
</body>
</html>"""


def _render_widget(widget: RenderedWidget, index: int) -> str:
    body = _render_widget_body(widget)
    error = (
        f'<p class="unavailable"><strong>Unavailable:</strong> {escape(widget.error)}</p>'
        if widget.error
        else ""
    )
    children = "".join(
        _render_widget(child, child_index)
        for child_index, child in enumerate(widget.children, 1)
    )
    return f"""<section class="report-section" id="{_anchor(widget.id)}">
  <p class="chapter-kicker">Section {index:02d}</p>
  <h1>{escape(widget.title)}</h1>
  {error}{body}{children}
</section>"""


def _render_widget_body(widget: RenderedWidget) -> str:
    data = widget.data
    if widget.type == "query_value":
        value = data.get("value", "unavailable")
        unit = data.get("unit") or widget.options.get("unit") or ""
        return (
            f'<div class="hero-value"><strong>{_value(value)}</strong>'
            f"<span>{_value(unit)}</span></div>"
        )
    columns = data.get("columns")
    rows = data.get("rows") or data.get("items")
    if _is_sequence(columns) and _is_sequence(rows):
        return _table(columns, rows)
    if widget.type in {"free_text", "note"} and data.get("body") is not None:
        return f'<div class="prose">{_multiline(data.get("body"))}</div>'
    if not data:
        return '<p class="unavailable">No evidence was available for this section.</p>'
    return _mapping_table(data)


def _table(columns: Any, rows: Any) -> str:
    safe_columns = [str(column) for column in columns]
    head = "".join(
        f"<th>{escape(column.replace('_', ' ').title())}</th>" for column in safe_columns
    )
    body_rows = []
    for raw_row in rows:
        row = raw_row if isinstance(raw_row, Mapping) else {"value": raw_row}
        cells = "".join(f"<td>{_value(row.get(column))}</td>" for column in safe_columns)
        body_rows.append(f"<tr>{cells}</tr>")
    if not body_rows:
        return '<p class="unavailable">No evidence rows were available.</p>'
    return (
        f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(body_rows)}</tbody></table></div>'
    )


def _mapping_table(data: Mapping[str, Any]) -> str:
    rows = "".join(
        f"<tr><th>{escape(str(key).replace('_', ' ').title())}</th><td>{_value(value)}</td></tr>"
        for key, value in data.items()
    )
    return f'<table class="key-value"><tbody>{rows}</tbody></table>'


def _value(value: Any) -> str:
    if value is None or value == "":
        return '<span class="muted">unavailable</span>'
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (Mapping, list, tuple)):
        return f"<code>{escape(json.dumps(value, sort_keys=True, default=str))}</code>"
    return escape(str(value))


def _multiline(value: Any) -> str:
    return "<br>".join(escape(str(value)).splitlines())


def _kpi(label: str, value: Any) -> str:
    return f'<div class="kpi"><span>{escape(label)}</span><strong>{_value(value)}</strong></div>'


def _anchor(value: str) -> str:
    return "report-" + "".join(character if character.isalnum() else "-" for character in value)


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def _load_css() -> str:
    resource = files("fdai.delivery.reporting").joinpath("assets/report.css")
    return resource.read_text(encoding="utf-8")


def _render_with_weasyprint(html: str, css: str) -> bytes:
    try:
        from weasyprint import CSS, HTML
    except (ImportError, OSError) as exc:
        raise PdfRenderUnavailableError(
            "PDF reporting requires the 'pdf-report' extra and WeasyPrint system libraries"
        ) from exc
    rendered = HTML(string=html).write_pdf(stylesheets=[CSS(string=css)])
    if not isinstance(rendered, bytes):
        raise PdfRenderUnavailableError("WeasyPrint did not return PDF bytes")
    return rendered


__all__ = [
    "PdfFormatEncoder",
    "PdfRenderUnavailableError",
    "install_pdf_format",
    "install_pdf_format_if_available",
    "render_report_html",
]
