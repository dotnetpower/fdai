"""Reporting domain models - inert dataclasses, no I/O, no framework deps.

Two families of shapes:

- **Spec** (:class:`ReportSpec`, :class:`WidgetSpec`, :class:`QuerySpec`,
  :class:`TimeRange`, :class:`Variable`) - what a report *declares*. Loaded
  from ``rule-catalog/reports/<id>.yaml`` by
  :mod:`fdai.core.reporting.catalog`.
- **Rendered** (:class:`RenderedReport`, :class:`RenderedWidget`,
  :class:`DataSet`, :class:`Series`) - what :class:`~fdai.core.reporting.engine.ReportEngine`
  returns after resolving every widget against its datasource.

Both families are frozen so a caller cannot mutate a rendered payload
after handoff (defense in depth for the read-only surface). ``to_dict``
on :class:`RenderedReport` is the canonical JSON shape the FE consumes;
the schema is documented in
[reporting-subsystem.md](../../../../docs/roadmap/interfaces/reporting-subsystem.md).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any


class TimeGrain(StrEnum):
    """Coarse aggregation grain a widget query may request.

    A datasource MAY ignore the hint and return the granularity it can
    honor - the caller MUST NOT assume the hint took effect (same rule as
    :class:`~fdai.shared.providers.metric.MetricQuery.aggregation`).
    """

    MINUTE = "1m"
    FIVE_MINUTE = "5m"
    FIFTEEN_MINUTE = "15m"
    HOUR = "1h"
    DAY = "1d"
    WEEK = "1w"


@dataclass(frozen=True, slots=True)
class TimeRange:
    """Absolute or relative report time window.

    A YAML entry ``time_range: {last: "1d"}`` becomes a
    ``TimeRange(relative_duration=timedelta(days=1))``; the engine
    resolves it against the render clock so caches never freeze the
    "now" reference.
    """

    since: datetime | None = None
    until: datetime | None = None
    relative_duration: timedelta | None = None

    def resolve(self, *, now: datetime) -> tuple[datetime, datetime]:
        """Return the concrete ``(since, until)`` pair for this render.

        Precedence: explicit ``(since, until)`` beats
        ``(since, relative_duration)`` beats ``(relative_duration, now)``.
        """
        if self.since is not None and self.until is not None:
            return (self.since, self.until)
        until = self.until or now
        if self.since is not None:
            return (self.since, until)
        if self.relative_duration is None:
            raise ValueError("TimeRange needs at least one of since / relative_duration")
        return (until - self.relative_duration, until)


@dataclass(frozen=True, slots=True)
class Variable:
    """A named parameter a caller may override at render time.

    ``values`` is an optional allowlist; when non-empty the engine
    rejects any override outside it (query params are untrusted input,
    ``coding-conventions.instructions.md § Error Handling and Boundaries``).
    """

    name: str
    default: str | None = None
    values: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True, slots=True)
class QuerySpec:
    """The abstract query a widget hands its datasource.

    ``datasource`` names the :class:`~fdai.core.reporting.contracts.ReportDataSource`
    entry in :class:`~fdai.core.reporting.registry.DataSourceRegistry`.
    ``parameters`` is the datasource-specific query body - opaque to the
    engine, forwarded verbatim after variable substitution.
    """

    datasource: str
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WidgetSpec:
    """One widget as declared in a report YAML.

    ``children`` is only meaningful for the composite ``group`` widget;
    for every other type the engine ignores it and calls the widget's
    :class:`~fdai.core.reporting.contracts.WidgetBuilder` with the
    datasource result.
    """

    id: str
    type: str
    title: str
    query: QuerySpec | None = None
    options: Mapping[str, Any] = field(default_factory=dict)
    children: tuple[WidgetSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class ReportSpec:
    """A full report declaration loaded from ``rule-catalog/reports/*.yaml``."""

    id: str
    version: str
    name: str
    description: str
    time_range: TimeRange
    variables: tuple[Variable, ...] = ()
    widgets: tuple[WidgetSpec, ...] = ()
    tags: tuple[str, ...] = ()


# ---- Rendered shapes (what the engine returns) ----------------------


@dataclass(frozen=True, slots=True)
class Series:
    """One labeled sequence of ``(epoch_seconds, value)`` points.

    Used by timeseries / heatmap / distribution-over-time widgets.
    ``labels`` carry the group-by tag values for one series - the FE
    renders them as legend chips.
    """

    label: str
    points: tuple[tuple[float, float], ...] = ()
    labels: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DataSet:
    """The generic result a datasource returns for one query.

    Shape is intentionally union-like: a datasource fills the fields that
    fit its result; widget builders read what they need and ignore the
    rest. This keeps the seam **one** (``ReportDataSource``) rather than
    fanning out to per-shape variants.

    - ``columns`` / ``rows``: tabular result (table, top-list, list).
    - ``series``: timeseries / heatmap / distribution-over-time result.
    - ``scalar``: single value result (query-value, change, slo-summary).
    - ``metadata``: opaque annotations (row totals, sample size, unit).
    """

    columns: tuple[str, ...] = ()
    rows: tuple[Mapping[str, Any], ...] = ()
    series: tuple[Series, ...] = ()
    scalar: float | int | str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RenderedWidget:
    """One widget after datasource + builder ran.

    ``data`` is the widget-specific payload (schema per widget type).
    ``error`` is set (and ``data`` is empty) when the widget could not
    render - a broken widget never fails the whole report, matching the
    fail-closed-per-signal pattern in
    :class:`~fdai.core.report_feed.feed.ReportFeed`.
    """

    id: str
    type: str
    title: str
    data: Mapping[str, Any]
    options: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    children: tuple[RenderedWidget, ...] = ()


@dataclass(frozen=True, slots=True)
class DataSourceProvenance:
    """Composition-owned origin and availability for one datasource slot."""

    datasource: str
    source: str
    availability: str = "unknown"
    synthetic: bool | None = None
    as_of: str | None = None

    def __post_init__(self) -> None:
        if self.availability not in {"available", "unavailable", "unknown"}:
            raise ValueError("datasource availability is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "datasource": self.datasource,
            "source": self.source,
            "availability": self.availability,
            "synthetic": self.synthetic,
            "as_of": self.as_of,
        }


@dataclass(frozen=True, slots=True)
class ReportProvenance:
    """Aggregate provenance for every query-backed widget in one render."""

    availability: str = "unknown"
    synthetic: bool | None = None
    sources: tuple[DataSourceProvenance, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "availability": self.availability,
            "synthetic": self.synthetic,
            "sources": [source.to_dict() for source in self.sources],
        }


@dataclass(frozen=True, slots=True)
class RenderedReport:
    """The engine's return value.

    ``generated_at`` and ``time_range`` are always UTC. ``variables`` is
    the resolved (defaults + validated overrides) map, not the raw
    overrides - so the audit / cache key derives from what was actually
    used.
    """

    id: str
    version: str
    name: str
    description: str
    generated_at: datetime
    time_range: tuple[datetime, datetime]
    variables: Mapping[str, str]
    widgets: tuple[RenderedWidget, ...]
    tags: tuple[str, ...] = ()
    provenance: ReportProvenance = field(default_factory=ReportProvenance)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable form; canonical FE contract."""
        return _rendered_report_to_dict(self)


def _rendered_report_to_dict(report: RenderedReport) -> dict[str, Any]:
    return {
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
        "widgets": [_rendered_widget_to_dict(w) for w in report.widgets],
        "tags": list(report.tags),
        "provenance": report.provenance.to_dict(),
    }


def _rendered_widget_to_dict(widget: RenderedWidget) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": widget.id,
        "type": widget.type,
        "title": widget.title,
        "data": dict(widget.data),
        "options": dict(widget.options),
    }
    if widget.error is not None:
        payload["error"] = widget.error
    if widget.children:
        payload["children"] = [_rendered_widget_to_dict(c) for c in widget.children]
    return payload


__all__ = [
    "DataSet",
    "DataSourceProvenance",
    "QuerySpec",
    "RenderedReport",
    "ReportProvenance",
    "RenderedWidget",
    "ReportSpec",
    "Series",
    "TimeGrain",
    "TimeRange",
    "Variable",
    "WidgetSpec",
]
