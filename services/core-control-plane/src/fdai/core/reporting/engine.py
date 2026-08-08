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

Runtime knobs live on :class:`~fdai.core.reporting.config.ReportEngineConfig`
(per-widget timeout, bounded parallelism, widget-count ceiling, error
message length cap). All fields default to safe values; a caller that
does not pass a config gets the historical sequential-in-declaration-order
behavior.

The engine does no caching. If a fork needs to serve identical renders
from a cache, wrap the engine in its own layer (composition root); the
engine's ``variables`` map is the natural cache key alongside the report
id and time range.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime

from fdai.core.reporting.config import ReportEngineConfig
from fdai.core.reporting.contracts import (
    DataSourceNotFoundError,
    ReportDataSource,
    VariableRejectedError,
    WidgetTypeNotFoundError,
)
from fdai.core.reporting.models import (
    DataSet,
    DataSourceProvenance,
    QuerySpec,
    RenderedReport,
    RenderedWidget,
    ReportProvenance,
    ReportSpec,
    WidgetSpec,
)
from fdai.core.reporting.registry import (
    DataSourceRegistry,
    ReportCatalog,
    WidgetRegistry,
)
from fdai.core.reporting.substitution import substitute
from fdai.core.reporting.widgets.composite import GROUP_LIKE_WIDGET_TYPES

_LOGGER = logging.getLogger(__name__)

Clock = Callable[[], datetime]
"""Deterministic-clock seam for tests / replay."""


class ReportEngine:
    """Render a :class:`ReportSpec` into a :class:`RenderedReport`.

    Composition-root wires the three registries once; every request-scope
    call is :meth:`render`.
    """

    __slots__ = ("_catalog", "_sources", "_widgets", "_clock", "_config")

    def __init__(
        self,
        *,
        catalog: ReportCatalog,
        sources: DataSourceRegistry,
        widgets: WidgetRegistry,
        clock: Clock | None = None,
        config: ReportEngineConfig | None = None,
    ) -> None:
        self._catalog = catalog
        self._sources = sources
        self._widgets = widgets
        self._clock = clock or _utcnow
        self._config = config or ReportEngineConfig()

    def catalog(self) -> ReportCatalog:
        return self._catalog

    def widget_registry(self) -> WidgetRegistry:
        return self._widgets

    def datasource_registry(self) -> DataSourceRegistry:
        return self._sources

    def config(self) -> ReportEngineConfig:
        return self._config

    def health(self) -> dict[str, object]:
        """Return a diagnostic snapshot of the engine's wired state.

        Emits registered names + counts only; never touches a datasource
        or renders a report. Read-only surface.
        """
        return {
            "reports": len(self._catalog.list()),
            "datasources": list(self._sources.names()),
            "widget_types": list(self._widgets.types()),
            "config": {
                "per_widget_timeout_seconds": self._config.per_widget_timeout_seconds,
                "max_concurrent_widgets": self._config.max_concurrent_widgets,
                "max_widgets_per_report": self._config.max_widgets_per_report,
                "max_error_message_chars": self._config.max_error_message_chars,
            },
        }

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
        provenance = self._report_provenance(spec.widgets)

        # Hard cap: a spec that would blow up the response body is
        # replaced with a single sentinel widget explaining why. The
        # count is over the whole widget tree so a deeply nested group
        # cannot smuggle in unlimited children.
        widget_count = _count_widgets(spec.widgets)
        max_widgets = self._config.max_widgets_per_report
        if widget_count > max_widgets:
            sentinel = self._make_error_widget(
                WidgetSpec(
                    id="_size_guard",
                    type="free_text",
                    title="Report too large",
                ),
                f"report {spec.id!r} declares {widget_count} widgets; "
                f"max_widgets_per_report={max_widgets}",
            )
            return RenderedReport(
                id=spec.id,
                version=spec.version,
                name=spec.name,
                description=spec.description,
                generated_at=now,
                time_range=(since, until),
                variables=resolved_vars,
                widgets=(sentinel,),
                tags=spec.tags,
                provenance=provenance,
            )

        rendered = await self._render_widgets(
            spec.widgets,
            since=since,
            until=until,
            variables=resolved_vars,
        )
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
            provenance=provenance,
        )

    def _report_provenance(self, widgets: Sequence[WidgetSpec]) -> ReportProvenance:
        names = sorted(_datasource_names(widgets))
        if not names:
            return ReportProvenance(availability="not_applicable")
        sources_list: list[DataSourceProvenance] = []
        for name in names:
            try:
                sources_list.append(self._sources.provenance(name))
            except DataSourceNotFoundError:
                sources_list.append(
                    DataSourceProvenance(
                        datasource=name,
                        source="unregistered",
                        availability="unavailable",
                    )
                )
        sources = tuple(sources_list)
        states = {source.availability for source in sources}
        availability = next(iter(states)) if len(states) == 1 else "partial"
        synthetic = (
            True
            if any(source.synthetic is True for source in sources)
            else False
            if all(source.synthetic is False for source in sources)
            else None
        )
        return ReportProvenance(
            availability=availability,
            synthetic=synthetic,
            sources=sources,
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
                        f"variable {name!r}={candidate!r} not in allowlist {sorted(var.values)!r}"
                    )
                resolved[name] = candidate
            elif var.default is not None:
                resolved[name] = var.default
        return resolved

    async def _render_widgets(
        self,
        widgets: Sequence[WidgetSpec],
        *,
        since: datetime,
        until: datetime,
        variables: Mapping[str, str],
        semaphore: asyncio.Semaphore | None = None,
    ) -> list[RenderedWidget]:
        # Reuse an outer semaphore when recursing into a group so the
        # concurrency ceiling applies across the whole render, not per
        # nesting level.
        limit = self._config.max_concurrent_widgets
        if semaphore is None and limit is not None:
            semaphore = asyncio.Semaphore(limit)

        if semaphore is None:
            # Sequential path - preserved default behavior.
            return [
                await self._render_widget(
                    w,
                    since=since,
                    until=until,
                    variables=variables,
                    semaphore=None,
                )
                for w in widgets
            ]

        async def _run(spec: WidgetSpec) -> RenderedWidget:
            # Group / tabs widgets are pure bookkeeping wrappers - they
            # never call a datasource, so they MUST NOT hold a permit
            # while their children (which do call a datasource) try to
            # acquire one. Otherwise a max_concurrent_widgets=1 config
            # deadlocks: the group parent owns the only permit and its
            # first child blocks forever waiting for it.
            if spec.type in GROUP_LIKE_WIDGET_TYPES:
                return await self._render_widget(
                    spec,
                    since=since,
                    until=until,
                    variables=variables,
                    semaphore=semaphore,
                )
            async with semaphore:
                return await self._render_widget(
                    spec,
                    since=since,
                    until=until,
                    variables=variables,
                    semaphore=semaphore,
                )

        # gather preserves declaration order in the return list even when
        # the underlying awaits complete out of order.
        return list(await asyncio.gather(*(_run(w) for w in widgets)))

    async def _render_widget(
        self,
        widget_spec: WidgetSpec,
        *,
        since: datetime,
        until: datetime,
        variables: Mapping[str, str],
        semaphore: asyncio.Semaphore | None,
    ) -> RenderedWidget:
        # Composite widgets (group / tabs) are special-cased - no
        # datasource call; recurse into declared children.
        if widget_spec.type in GROUP_LIKE_WIDGET_TYPES:
            children = await self._render_widgets(
                widget_spec.children,
                since=since,
                until=until,
                variables=variables,
                semaphore=semaphore,
            )
            return RenderedWidget(
                id=widget_spec.id,
                type=widget_spec.type,
                title=widget_spec.title,
                data={},
                options=widget_spec.options,
                children=tuple(children),
            )

        try:
            builder = self._widgets.get(widget_spec.type)
        except WidgetTypeNotFoundError as exc:
            return self._make_error_widget(widget_spec, f"unknown widget type: {exc}")

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
                return self._make_error_widget(
                    widget_spec, f"builder error: {type(exc).__name__}: {exc}"
                )
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
            return self._make_error_widget(widget_spec, f"unknown datasource: {exc}")

        # Resolve `$var` / `${var}` references inside `parameters` once,
        # after variables were validated. Undeclared references raise
        # VariableRejectedError and become an error widget.
        try:
            resolved_params = substitute(widget_spec.query.parameters, variables)
        except VariableRejectedError as exc:
            return self._make_error_widget(widget_spec, str(exc))
        query = QuerySpec(
            datasource=widget_spec.query.datasource,
            parameters=resolved_params if isinstance(resolved_params, Mapping) else {},
        )

        try:
            dataset = await self._invoke_source(
                source,
                query,
                since=since,
                until=until,
                variables=variables,
            )
        except TimeoutError:
            _LOGGER.warning(
                "reporting_datasource_timeout",
                extra={
                    "widget_id": widget_spec.id,
                    "datasource": widget_spec.query.datasource,
                    "timeout_seconds": self._config.per_widget_timeout_seconds,
                },
            )
            return self._make_error_widget(
                widget_spec,
                f"datasource timeout after {self._config.per_widget_timeout_seconds}s",
            )
        except Exception as exc:  # noqa: BLE001 - isolate one datasource
            _LOGGER.warning(
                "reporting_datasource_failed",
                extra={
                    "widget_id": widget_spec.id,
                    "datasource": widget_spec.query.datasource,
                },
            )
            return self._make_error_widget(
                widget_spec, f"datasource error: {type(exc).__name__}: {exc}"
            )

        try:
            data = builder.build(spec=widget_spec, data=dataset)
        except Exception as exc:  # noqa: BLE001 - isolate one builder
            _LOGGER.warning(
                "reporting_widget_build_failed",
                extra={"widget_id": widget_spec.id, "widget_type": widget_spec.type},
            )
            return self._make_error_widget(
                widget_spec, f"builder error: {type(exc).__name__}: {exc}"
            )

        return RenderedWidget(
            id=widget_spec.id,
            type=widget_spec.type,
            title=widget_spec.title,
            data=data,
            options=widget_spec.options,
        )

    async def _invoke_source(
        self,
        source: ReportDataSource,
        query: QuerySpec,
        *,
        since: datetime,
        until: datetime,
        variables: Mapping[str, str],
    ) -> DataSet:
        coro = source.query(query, since=since, until=until, variables=variables)
        timeout = self._config.per_widget_timeout_seconds
        if timeout is None:
            return await coro
        result = await asyncio.wait_for(coro, timeout=timeout)
        return result

    def _make_error_widget(self, spec: WidgetSpec, message: str) -> RenderedWidget:
        capped = _cap(message, self._config.max_error_message_chars)
        return RenderedWidget(
            id=spec.id,
            type=spec.type,
            title=spec.title,
            data={},
            options=spec.options,
            error=capped,
        )


def _count_widgets(widgets: Sequence[WidgetSpec]) -> int:
    total = 0
    for widget in widgets:
        total += 1
        if widget.children:
            total += _count_widgets(widget.children)
    return total


def _datasource_names(widgets: Sequence[WidgetSpec]) -> set[str]:
    names = {widget.query.datasource for widget in widgets if widget.query is not None}
    for widget in widgets:
        names.update(_datasource_names(widget.children))
    return names


def _cap(message: str, limit: int) -> str:
    if len(message) <= limit:
        return message
    marker = " ...truncated"
    if limit <= len(marker):
        return message[:limit]
    return message[: limit - len(marker)] + marker


def _utcnow() -> datetime:
    return datetime.now(UTC)


__all__ = ["Clock", "ReportEngine"]


__all__ = ["Clock", "ReportEngine"]
