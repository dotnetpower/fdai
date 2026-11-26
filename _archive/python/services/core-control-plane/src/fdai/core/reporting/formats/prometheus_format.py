"""Prometheus text-exposition format encoder.

Emits ``# HELP`` / ``# TYPE`` / sample lines from scalar and timeseries
widgets so a Prometheus scrape can consume the same report a browser
does. Non-numeric widgets are dropped from the output; the encoder is
best-effort and geared toward KPI dashboards that are already
number-shaped (query_value, timeseries, sparkline).

Metric naming: ``fdai_report_<report_id>_<widget_id>`` with dots /
dashes replaced by underscores. Values are the widget's ``value`` (for
scalars) or the last point of each series (for series widgets).

Not registered by default - Prometheus is a specific consumer and the
metric namespace is opinionated. A fork opts in by registering it on
its FormatRegistry.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from fdai.core.reporting.models import RenderedReport, RenderedWidget

_SANITIZE = re.compile(r"[^A-Za-z0-9_]")


class PrometheusFormatEncoder:
    """Serialize a :class:`RenderedReport` to Prometheus text-exposition bytes."""

    name = "prometheus"
    content_type = "text/plain; version=0.0.4; charset=utf-8"

    def encode(self, report: RenderedReport) -> bytes:
        lines: list[str] = []
        for widget in report.widgets:
            self._emit_widget(widget, report_id=report.id, lines=lines)
        return ("\n".join(lines) + "\n").encode("utf-8")

    def _emit_widget(
        self,
        widget: RenderedWidget,
        *,
        report_id: str,
        lines: list[str],
    ) -> None:
        if widget.error is not None:
            return
        title = _sanitize_help(widget.title)
        if widget.type == "query_value":
            value = _as_float(widget.data.get("value"))
            if value is None:
                return
            metric = _metric_name(report_id, widget.id)
            lines.append(f"# HELP {metric} {title}")
            lines.append(f"# TYPE {metric} gauge")
            lines.append(f"{metric} {value}")
        elif widget.type in ("timeseries", "heatmap", "sparkline"):
            metric = _metric_name(report_id, widget.id)
            lines.append(f"# HELP {metric} {title}")
            lines.append(f"# TYPE {metric} gauge")
            for entry in widget.data.get("series") or ():
                if not isinstance(entry, Mapping):
                    continue
                label = str(entry.get("label", ""))
                last = _last_value(entry)
                if last is None:
                    continue
                labels_str = f'series="{_escape_label(label)}"'
                lines.append(f"{metric}{{{labels_str}}} {last}")
        elif widget.type in ("group", "tabs"):
            for child in widget.children:
                self._emit_widget(child, report_id=report_id, lines=lines)


def _metric_name(report_id: str, widget_id: str) -> str:
    return "fdai_report_" + _SANITIZE.sub("_", f"{report_id}_{widget_id}")


def _sanitize_help(value: str) -> str:
    """Collapse whitespace and drop line breaks so a HELP line is one line.

    Prometheus text-exposition format expects HELP / TYPE / sample
    on separate lines; a title carrying ``\\n`` would silently split
    into a bogus new directive and break scrape parsing. Backslashes
    are escaped per the exposition-format spec.
    """
    if not value:
        return "(no title)"
    escaped = value.replace("\\", "\\\\").replace("\n", " ").replace("\r", " ")
    return escaped.strip() or "(no title)"


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _last_value(entry: Mapping[str, Any]) -> float | None:
    points = entry.get("points")
    if points:
        try:
            return float(points[-1][1])
        except (IndexError, TypeError, ValueError):
            return None
    values = entry.get("values")
    if values:
        try:
            return float(values[-1])
        except (IndexError, TypeError, ValueError):
            return None
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["PrometheusFormatEncoder"]
