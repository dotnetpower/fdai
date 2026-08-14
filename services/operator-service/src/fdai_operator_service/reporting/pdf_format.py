"""Render materialized report envelopes as bounded, read-only PDF documents."""

from __future__ import annotations

import hashlib
import html
import json
from collections.abc import Mapping, Sequence
from typing import Final, Never

from weasyprint import HTML

from fdai_operator_service.families.operations import ReportPdfEncodingError

MAX_ENVELOPE_BYTES: Final = 2 * 1024 * 1024
MAX_WIDGETS: Final = 200
MAX_PAGES: Final = 250

_STYLE: Final = """
@page {
  size: A4;
  margin: 18mm 16mm 20mm;
  @bottom-center {
    content: "FDAI read-only report | page " counter(page) " of " counter(pages);
    color: #52606d;
    font: 8pt sans-serif;
  }
}
body { color: #18212b; font: 10pt/1.45 sans-serif; }
h1 { font-size: 20pt; margin: 0 0 4mm; }
h2 { font-size: 14pt; margin: 0 0 3mm; }
.meta, .provenance { background: #f2f5f7; padding: 4mm; }
.digest { font: 8pt monospace; overflow-wrap: anywhere; }
.widget { break-before: page; }
.widget.first { break-before: auto; }
.unavailable { border: 1px solid #b42318; padding: 3mm; }
dl { display: grid; grid-template-columns: minmax(32mm, 1fr) 3fr; gap: 1mm 3mm; }
dt { font-weight: 700; }
dd { margin: 0; overflow-wrap: anywhere; }
table { border-collapse: collapse; width: 100%; table-layout: fixed; }
th, td {
    border: 0.3pt solid #9aa5b1;
    padding: 1.5mm;
    vertical-align: top;
    overflow-wrap: anywhere;
}
th { background: #e8edf1; text-align: left; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font: 8pt/1.35 monospace; }
"""


class PdfReportEncoder:
    """Arrange one existing report envelope without adding analysis or authority."""

    name = "pdf"
    content_type = "application/pdf"

    def encode(self, report: Mapping[str, object]) -> bytes:
        """Render a bounded A4 PDF with source digest and explicit gaps."""
        canonical = _canonical_envelope(report)
        digest = hashlib.sha256(canonical).hexdigest()
        markup = _report_html(report, digest=digest)
        fetch_guard = _ExternalFetchGuard()
        try:
            document = HTML(string=markup, url_fetcher=fetch_guard).render()
            if fetch_guard.attempted:
                raise ReportPdfEncodingError("external resources are prohibited in report PDFs")
            if not 1 <= len(document.pages) <= MAX_PAGES:
                raise ReportPdfEncodingError("report PDF page count is outside the allowed bound")
            payload = document.write_pdf()
        except ReportPdfEncodingError:
            raise
        except Exception as exc:
            raise ReportPdfEncodingError("report PDF rendering failed") from exc
        if not isinstance(payload, bytes) or not payload.startswith(b"%PDF-"):
            raise ReportPdfEncodingError("report PDF renderer returned an invalid payload")
        return payload


def source_envelope_digest(report: Mapping[str, object]) -> str:
    """Return the stable SHA-256 digest bound into the rendered PDF."""
    return hashlib.sha256(_canonical_envelope(report)).hexdigest()


def _canonical_envelope(report: Mapping[str, object]) -> bytes:
    _required_string(report, "id")
    _required_string(report, "version")
    _required_string(report, "name")
    _required_string(report, "generated_at")
    widgets = report.get("widgets")
    if not isinstance(widgets, Sequence) or isinstance(widgets, (str, bytes)):
        raise ReportPdfEncodingError("report widgets MUST be an array")
    if len(widgets) > MAX_WIDGETS or any(not isinstance(widget, Mapping) for widget in widgets):
        raise ReportPdfEncodingError("report widgets exceed the supported shape")
    try:
        encoded = json.dumps(
            report,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReportPdfEncodingError("report envelope is not canonical JSON") from exc
    if len(encoded) > MAX_ENVELOPE_BYTES:
        raise ReportPdfEncodingError("report envelope exceeds the PDF input bound")
    return encoded


def _report_html(report: Mapping[str, object], *, digest: str) -> str:
    widgets = report.get("widgets")
    if not isinstance(widgets, Sequence) or isinstance(widgets, (str, bytes)):
        raise ReportPdfEncodingError("report widgets MUST be an array")
    sections = [
        _widget_html(widget, first=index == 0)
        for index, widget in enumerate(widgets)
        if isinstance(widget, Mapping)
    ]
    provenance = report.get("provenance")
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{_STYLE}</style></head><body>"
        f"<h1>{_escape(report['name'])}</h1>"
        f"<p>{_escape(report.get('description', ''))}</p>"
        "<section class='meta'><h2>Report envelope</h2><dl>"
        f"<dt>Report id</dt><dd>{_escape(report['id'])}</dd>"
        f"<dt>Version</dt><dd>{_escape(report['version'])}</dd>"
        f"<dt>Generated at</dt><dd>{_escape(report['generated_at'])}</dd>"
        f"<dt>Source digest</dt><dd class='digest'>sha256:{digest}</dd>"
        "<dt>Authority</dt>"
        "<dd>Read-only presentation. No new analysis or execution authority.</dd>"
        "</dl></section>"
        "<section class='provenance'><h2>Evidence provenance</h2>"
        f"{_value_html(provenance)}</section>" + "".join(sections) + "</body></html>"
    )


def _widget_html(widget: Mapping[str, object], *, first: bool) -> str:
    title = _escape(widget.get("title", "Untitled section"))
    error = widget.get("error")
    if isinstance(error, str) and error:
        state = (
            "<div class='unavailable'><strong>Unavailable section</strong>"
            f"<p>{_escape(error)}</p></div>"
        )
    else:
        state = _value_html(widget.get("data"))
    css_class = "widget first" if first else "widget"
    return (
        f"<section class='{css_class}'><h2>{title}</h2><dl>"
        f"<dt>Widget id</dt><dd>{_escape(widget.get('id', ''))}</dd>"
        f"<dt>Widget type</dt><dd>{_escape(widget.get('type', ''))}</dd>"
        f"</dl>{state}</section>"
    )


def _value_html(value: object) -> str:
    if isinstance(value, Mapping):
        if _is_table(value):
            return _table_html(value)
        return (
            "<dl>"
            + "".join(
                f"<dt>{_escape(key)}</dt><dd>{_value_html(item)}</dd>"
                for key, item in value.items()
            )
            + "</dl>"
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return "<ol>" + "".join(f"<li>{_value_html(item)}</li>" for item in value) + "</ol>"
    if value is None:
        return "<span>Unavailable</span>"
    return f"<span>{_escape(value)}</span>"


def _is_table(value: Mapping[object, object]) -> bool:
    columns = value.get("columns")
    rows = value.get("rows")
    return (
        isinstance(columns, Sequence)
        and not isinstance(columns, (str, bytes))
        and isinstance(rows, Sequence)
        and not isinstance(rows, (str, bytes))
    )


def _table_html(value: Mapping[object, object]) -> str:
    columns = value.get("columns")
    rows = value.get("rows")
    if (
        not isinstance(columns, Sequence)
        or isinstance(columns, (str, bytes))
        or not isinstance(rows, Sequence)
        or isinstance(rows, (str, bytes))
    ):
        raise ReportPdfEncodingError("report table data is malformed")
    safe_columns = [str(column) for column in columns]
    body = []
    for row in rows:
        if isinstance(row, Mapping):
            body.append(
                "<tr>"
                + "".join(f"<td>{_value_html(row.get(column))}</td>" for column in safe_columns)
                + "</tr>"
            )
        elif isinstance(row, Sequence) and not isinstance(row, (str, bytes)):
            body.append("<tr>" + "".join(f"<td>{_value_html(item)}</td>" for item in row) + "</tr>")
    return (
        "<table><thead><tr>"
        + "".join(f"<th>{_escape(column)}</th>" for column in safe_columns)
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def _required_string(report: Mapping[str, object], key: str) -> str:
    value = report.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ReportPdfEncodingError(f"report {key} MUST be a non-empty string")
    return value


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


class _ExternalFetchGuard:
    """Block and remember every resource request attempted by generated markup."""

    def __init__(self) -> None:
        self.attempted = False

    def __call__(
        self,
        url: str,
        timeout: int = 10,
        ssl_context: object | None = None,
    ) -> Never:
        del url, timeout, ssl_context
        self.attempted = True
        raise ReportPdfEncodingError("external resources are prohibited in report PDFs")


__all__ = ["PdfReportEncoder", "source_envelope_digest"]
