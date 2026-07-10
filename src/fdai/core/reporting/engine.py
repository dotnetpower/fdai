"""ReportEngine - orchestrates catalog -> datasource -> builder -> render.

Read-only by contract. Per-widget errors are isolated so a broken
datasource or a bogus builder never fails the whole report - the
offending widget is rendered with ``error`` set and empty ``data``, and
the caller still gets every other widget. This mirrors
:class:`~fdai.core.report_feed.feed.ReportFeed`'s "one bad source never
drops the whole feed" pattern.

Variable resolution is fail-closed:

- overrides referencing an undeclared variable are rejected;
- overrides outside a declared ``values`` allowlist are rejected;
- both cases raise :class:`~fdai.core.reporting.contracts.VariableRejectedError`
  before any datasource is touched.

The engine does no caching. If a fork needs to serve identical renders
from a cache, wrap the engine in its own layer (composition root); the
engine's ``variables`` map is the natural cache key alongside the report
id and time range.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from fdai.core.reporting.contracts import (
    DataSourceNotFoundError,
    VariableRejectedError,
    WidgetTypeNotFoundError,
)
from fdai.core.reporting.models import (
    DataSet,
    RenderedReport,
    RenderedWidget,
    ReportSpec,
    WidgetSpec,
)
from fdai.core.reporting.registry import (
    DataSourceRegistry,
    ReportCatalog,
    WidgetRegistry,
)

_LOGGER = logging.getLogger(__name__)

Clock = Callable[[], datetime]
"""Deterministic-clock seam for tests / replay."""

_GROUP_WIDGET_TYPE = "group"


class ReportEngine:
    """Render a :class:`ReportSpec` into a :class:`RenderedReport`.

    Composition-root wires the three registries once; every request-scope
    call is :meth:`render` (async, awaits each datasource in declaration
    order).
    """

    __slots__ = ("_catalog", "_sources", "_widgets", "_clock")

    def __init__(
        self,
        *,
        catalog: ReportCatalog,
        sources: DataSourceRegistry,
        widgets: WidgetRegistry,
        clock: Clock | None = None,
    ) -> None:
        self._catalog = catalog
        self._sources = sources
        self._widgets = widgets
        self._clock = clock or _utcnow

    def catalog(self) -> ReportCatalog:
        return self._catalog

    def widget_registry(self) -> WidgetRegistry:
        return self._widgets

    def datasource_registry(self) -> DataSourceRegistry:
        return self._sources

    async def render(
        self,
        report_id: str,
        *,
        variables: Mapping[str, str] | None = None,
    ) -> RenderedReport:
        """Render ``report_id`` with optional variable overrides."""
        spec = self._catalog.get(report_id)
        resolved_vars = self._resolve_variables(spec, variables or {})
        now = self._clock()
        since, until = spec.time_range.resolve(now=now)
        rendered = [
            await self._render_widget(w, since=since, until=until, variables=resolved_vars)
            for w in spec.widgets
        ]
        return RenderedReport(
            id=spec.id,
            version=spec.version,
            name=spec.name,
            description=spec.description,
            generated_at=now,
            time_range=(since, until),
            variables=resolved_vars,
            widgets=tuple(rendered),
            tags=spec.tags,
        )

    def _resolve_variables(
        self,
        spec: ReportSpec,
        overrides: Mapping[str, str],
    ) -> dict[str, str]:
        declared = {v.name: v for v in spec.variables}
        # Reject unknown overrides before touching anything else - a caller
        # who mistypes a variable name gets a clear failure, not a
        # silently-ignored parameter.
        for name in overrides:
            if name not in declared:
                raise VariableRejectedError(f"unknown variable {name!r}")
        resolved: dict[str, str] = {}
        for name, var in declared.items():
            if name in overrides:
                candidate = overrides[name]
                if var.values and candidate not in var.values:
                    raise VariableRejectedError(
                        f"variable {name!r}={candidate!r} not in allowlist "
                        f"{sorted(var.values)!r}"
                    )
                resolved[name] = candidate
            elif var.default is not None:
                resolved[name] = var.default
        return resolved

    async def _render_widget(
        self,
        widget_spec: WidgetSpec,
        *,
        since: datetime,
        until: datetime,
        variables: Mapping[str, str],
    ) -> RenderedWidget:
        # Group widgets are composite - recurse; no datasource call.
        if widget_spec.type == _GROUP_WIDGET_TYPE:
            children = [
                await self._render_widget(
                    child, since=since, until=until, variables=variables
                )
                for child in widget_spec.children
            ]
            return RenderedWidget(
                id=widget_spec.id,
                type=_GROUP_WIDGET_TYPE,
                title=widget_spec.title,
                data={},
                options=widget_spec.options,
                children=tuple(children),
            )

        try:
            builder = self._widgets.get(widget_spec.type)
        except WidgetTypeNotFoundError as exc:
            return _error_widget(widget_spec, f"unknown widget type: {exc}")

        # Annotation widgets (free_text, notes, image) carry their whole
        # payload in `options` and skip the datasource step.
        if widget_spec.query is None:
            try:
                data = builder.build(spec=widget_spec, data=DataSet())
            except Exception as exc:  # noqa: BLE001 - isolate one builder
                _LOGGER.warning(
                    "reporting_annotation_build_failed",
                    extra={"widget_id": widget_spec.id, "widget_type": widget_spec.type},
                )
                return _error_widget(widget_spec, f"builder error: {type(exc).__name__}: {exc}")
            return RenderedWidget(
                id=widget_spec.id,
                type=widget_spec.type,
                title=widget_spec.title,
                data=data,
                options=widget_spec.options,
            )

        try:
            source = self._sources.get(widget_spec.query.datasource)
        except DataSourceNotFoundError as exc:
            return _error_widget(widget_spec, f"unknown datasource: {exc}")

        try:
            dataset = await source.query(
                widget_spec.query,
                since=since,
                until=until,
                variables=variables,
            )
        except Exception as exc:  # noqa: BLE001 - isolate one datasource
            _LOGGER.warning(
                "reporting_datasource_failed",
                extra={
                    "widget_id": widget_spec.id,
                    "datasource": widget_spec.query.datasource,
                },
            )
            return _error_widget(
                widget_spec, f"datasource error: {type(exc).__name__}: {exc}"
            )

        try:
            data = builder.build(spec=widget_spec, data=dataset)
        except Exception as exc:  # noqa: BLE001 - isolate one builder
            _LOGGER.warning(
                "reporting_widget_build_failed",
                extra={"widget_id": widget_spec.id, "widget_type": widget_spec.type},
            )
            return _error_widget(
                widget_spec, f"builder error: {type(exc).__name__}: {exc}"
            )

        return RenderedWidget(
            id=widget_spec.id,
            type=widget_spec.type,
            title=widget_spec.title,
            data=data,
            options=widget_spec.options,
        )


def _error_widget(spec: WidgetSpec, message: str) -> RenderedWidget:
    return RenderedWidget(
        id=spec.id,
        type=spec.type,
        title=spec.title,
        data={},
        options=spec.options,
        error=message,
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


__all__ = ["Clock", "ReportEngine"]
