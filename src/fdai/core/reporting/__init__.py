"""Reporting subsystem - declarative, extensible visualization pipeline.

The reporting subsystem lets a fork declare **any number of report shapes**
(time-series overviews, top-N tables, cost summaries, SLO burn boards,
signal-feed rollups) in YAML under ``rule-catalog/reports/`` and render
them through one framework-neutral engine. The engine composes three
registries - datasources, widget builders, and format encoders - so
adding a new visualization is a matter of:

1. **New data**: implement :class:`~fdai.core.reporting.contracts.ReportDataSource`
   and register it at the composition root.
2. **New shape**: implement :class:`~fdai.core.reporting.contracts.WidgetBuilder`
   and register it.
3. **New report**: drop a YAML file under ``rule-catalog/reports/``.
4. **New export**: implement :class:`~fdai.core.reporting.contracts.FormatEncoder`
   and register it.

The frontend is **not** required to change: every rendered report is a
strict JSON document with a Datadog-inspired widget schema
(``{id, type, title, data, options}``), so the console SPA is a generic
renderer keyed on ``type``. See
[docs/roadmap/reporting-subsystem.md](../../../../docs/roadmap/reporting-subsystem.md).

Read-only by contract: the entire subsystem never mutates state, never
holds the executor identity, and every route wired via
:mod:`fdai.delivery.read_api.reporting` is ``GET``-only. This matches the
console invariant in ``app-shape.instructions.md``.
"""

from __future__ import annotations

from fdai.core.reporting.contracts import (
    DataSourceNotFoundError,
    FormatEncoder,
    FormatNotFoundError,
    ReportDataSource,
    ReportingError,
    ReportNotFoundError,
    VariableRejectedError,
    WidgetBuilder,
    WidgetTypeNotFoundError,
)
from fdai.core.reporting.engine import Clock, ReportEngine
from fdai.core.reporting.models import (
    DataSet,
    QuerySpec,
    RenderedReport,
    RenderedWidget,
    ReportSpec,
    Series,
    TimeGrain,
    TimeRange,
    Variable,
    WidgetSpec,
)
from fdai.core.reporting.registry import (
    DataSourceRegistry,
    FormatRegistry,
    ReportCatalog,
    WidgetRegistry,
)

__all__ = [
    "Clock",
    "DataSet",
    "DataSourceNotFoundError",
    "DataSourceRegistry",
    "FormatEncoder",
    "FormatNotFoundError",
    "FormatRegistry",
    "QuerySpec",
    "RenderedReport",
    "RenderedWidget",
    "ReportCatalog",
    "ReportDataSource",
    "ReportEngine",
    "ReportNotFoundError",
    "ReportSpec",
    "ReportingError",
    "Series",
    "TimeGrain",
    "TimeRange",
    "Variable",
    "VariableRejectedError",
    "WidgetBuilder",
    "WidgetRegistry",
    "WidgetSpec",
    "WidgetTypeNotFoundError",
]
