"""NDJSON format encoder - one JSON object per line.

Great for `jq` pipelines and streaming ingest: the first line is the
report header (without widgets), and every subsequent line is one
widget. A consumer that only cares about widget shapes ignores the
header and streams the rest.
"""

from __future__ import annotations

import json

from fdai.core.reporting.models import RenderedReport, RenderedWidget


class NdjsonFormatEncoder:
    """Serialize a :class:`RenderedReport` to a UTF-8 NDJSON body."""

    name = "ndjson"
    content_type = "application/x-ndjson"

    def encode(self, report: RenderedReport) -> bytes:
        lines: list[str] = []
        header = {
            "kind": "report",
            "id": report.id,
            "version": report.version,
            "name": report.name,
            "description": report.description,
            "generated_at": report.generated_at.isoformat(),
            "time_range": {
                "since": report.time_range[0].isoformat(),
                "until": report.time_range[1].isoformat(),
            },
            "variables": dict(report.variables),
            "tags": list(report.tags),
        }
        lines.append(json.dumps(header, ensure_ascii=False))
        for widget in report.widgets:
            for entry in _flatten(widget, parent=None):
                lines.append(json.dumps(entry, ensure_ascii=False))
        # Trailing newline keeps `wc -l` and line-oriented tools happy.
        return ("\n".join(lines) + "\n").encode("utf-8")


def _flatten(widget: RenderedWidget, *, parent: str | None) -> list[dict[str, object]]:
    entry: dict[str, object] = {
        "kind": "widget",
        "id": widget.id,
        "type": widget.type,
        "title": widget.title,
        "data": dict(widget.data),
        "options": dict(widget.options),
    }
    if widget.error is not None:
        entry["error"] = widget.error
    if parent is not None:
        entry["parent"] = parent
    out = [entry]
    for child in widget.children:
        out.extend(_flatten(child, parent=widget.id))
    return out


__all__ = ["NdjsonFormatEncoder"]
