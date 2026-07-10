"""Read-only reporting routes for the console API.

Exposes the :class:`~fdai.core.reporting.engine.ReportEngine` over four
``GET`` endpoints so a fork adds new reports (YAML) or new datasources
(one Protocol implementation at the composition root) without ever
touching this file.

Routes (all under a configurable prefix, default ``/reports``):

- ``GET /reports`` - catalog listing (id, name, description, version,
  tags, variables schema, widget count).
- ``GET /reports/registry`` - registered datasource / widget-type /
  format names. Useful for a FE picker or "what is wired here?"
  diagnostic.
- ``GET /reports/{id}`` - one report's full declaration (a JSON
  projection of the loaded :class:`ReportSpec`).
- ``GET /reports/{id}/render`` - the rendered payload. Query params
  become variable overrides; ``?format=<name>`` picks a
  :class:`FormatEncoder` (``json`` default).

Read-only invariant is preserved: **no POST / PUT / DELETE / PATCH**;
each route calls the shared ``authorize`` closure and matches the
reader-role gate used by the core routes. See
``app-shape.instructions.md § Operator console``.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.reporting.contracts import (
    FormatNotFoundError,
    ReportNotFoundError,
    VariableRejectedError,
)
from fdai.core.reporting.engine import ReportEngine
from fdai.core.reporting.models import ReportSpec, WidgetSpec
from fdai.core.reporting.registry import FormatRegistry

_LOGGER = logging.getLogger(__name__)

Authorize = Callable[[Request], Awaitable[str]]
"""The shared read-API authorize closure - returns the caller's ``oid``."""

_FORMAT_QUERY_PARAM = "format"
_DEFAULT_FORMAT = "json"

# Mirrors the JSON Schema pattern in
# `rule-catalog/reports/schema/report.schema.json`. The path parameter
# is validated at the handler edge so a probe like `../../etc/passwd`
# never reaches the catalog lookup (Starlette's `:str` converter
# already refuses slashes, but this guard also blocks empty / weird
# ids and keeps the 404 log line free of attacker-supplied noise).
_REPORT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
# ``?format=`` values are matched against the FormatRegistry, but a
# malformed value should short-circuit *before* the registry lookup so
# the log line never records an attacker-controlled string.
_FORMAT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
# Variable names are declared in YAML with the same regex as the JSON
# Schema on ``variable.name``. Reject any override whose name does not
# match up-front so an attacker-controlled key never lands in a log
# line or in a downstream substitution attempt.
_VARIABLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True, slots=True)
class ReportingConfig:
    """Composition-root configuration for :func:`build_reporting_routes`.

    ``engine`` and ``formats`` are wired at the composition root - the
    engine holds the datasource / widget registries and the loaded
    :class:`ReportCatalog`; the format registry is separate so a fork
    can add its own encoder (PDF, XLSX) without touching the engine.

    ``prefix`` MUST start with ``/`` and MUST NOT collide with an
    existing route or panel; :func:`build_reporting_routes` validates.
    """

    engine: ReportEngine
    formats: FormatRegistry
    prefix: str = "/reports"
    default_format: str = _DEFAULT_FORMAT


def build_reporting_routes(
    *,
    config: ReportingConfig,
    authorize: Authorize,
    core_paths: frozenset[str] | None = None,
    seen_extra_paths: set[str] | None = None,
) -> list[Route]:
    """Return the reporting routes ready to append to a Starlette app.

    Fails fast on prefix conflicts so a bad composition can never ship
    a broken revision. ``seen_extra_paths`` is mutated to include the
    reporting routes so a subsequent panel cannot collide with them.
    """
    prefix = config.prefix.rstrip("/") or "/reports"
    if not prefix.startswith("/"):
        raise ValueError(f"reporting.prefix MUST start with '/', got {prefix!r}")

    endpoint_paths = {
        f"{prefix}",
        f"{prefix}/registry",
        f"{prefix}/formats",
        f"{prefix}/widget-types",
        f"{prefix}/datasources",
        f"{prefix}/health",
    }
    if core_paths is not None:
        for path in endpoint_paths:
            if path in core_paths:
                raise ValueError(f"reporting route {path!r} collides with a core route")
    if seen_extra_paths is not None:
        for path in endpoint_paths:
            if path in seen_extra_paths:
                raise ValueError(f"reporting route {path!r} collides with an extra route")
        seen_extra_paths.update(endpoint_paths)
        # Prefix-based paths (``/reports/{id}``) are matched by pattern,
        # not by an exact string; record only the exact-match endpoints.

    if config.default_format not in config.formats.names():
        raise ValueError(
            f"default_format {config.default_format!r} not registered "
            f"(known: {list(config.formats.names())})"
        )

    engine = config.engine
    formats = config.formats
    default_format = config.default_format

    async def list_reports(request: Request) -> Response:
        oid = await authorize(request)
        specs = engine.catalog().list()
        payload = {
            "items": [_summarize_spec(spec) for spec in specs],
            "formats": list(formats.names()),
        }
        _LOGGER.info(
            "reporting_listed",
            extra={"actor": oid, "count": len(specs)},
        )
        return JSONResponse(payload)

    async def get_registry(request: Request) -> Response:
        oid = await authorize(request)
        payload = {
            "datasources": list(engine.datasource_registry().names()),
            "widgets": list(engine.widget_registry().types()),
            "formats": list(formats.names()),
        }
        _LOGGER.info("reporting_registry_served", extra={"actor": oid})
        return JSONResponse(payload)

    async def list_formats(request: Request) -> Response:
        oid = await authorize(request)
        items = [
            {"name": encoder.name, "content_type": encoder.content_type}
            for encoder in (formats.get(name) for name in formats.names())
        ]
        _LOGGER.info("reporting_formats_served", extra={"actor": oid})
        return JSONResponse({"items": items})

    async def list_widget_types(request: Request) -> Response:
        oid = await authorize(request)
        _LOGGER.info("reporting_widget_types_served", extra={"actor": oid})
        return JSONResponse({"items": list(engine.widget_registry().types())})

    async def list_datasource_names(request: Request) -> Response:
        oid = await authorize(request)
        _LOGGER.info("reporting_datasources_served", extra={"actor": oid})
        return JSONResponse({"items": list(engine.datasource_registry().names())})

    async def get_health(request: Request) -> Response:
        oid = await authorize(request)
        _LOGGER.info("reporting_health_served", extra={"actor": oid})
        return JSONResponse(engine.health())

    async def get_report(request: Request) -> Response:
        oid = await authorize(request)
        report_id = request.path_params["report_id"]
        if not _REPORT_ID_RE.fullmatch(report_id):
            return _error(400, "malformed report id")
        try:
            spec = engine.catalog().get(report_id)
        except ReportNotFoundError:
            return _error(404, f"report {report_id!r} not found")
        _LOGGER.info(
            "reporting_definition_served",
            extra={"actor": oid, "report_id": report_id},
        )
        return JSONResponse(_full_spec_payload(spec))

    async def render_report(request: Request) -> Response:
        oid = await authorize(request)
        report_id = request.path_params["report_id"]
        if not _REPORT_ID_RE.fullmatch(report_id):
            return _error(400, "malformed report id")
        raw_params = dict(request.query_params)
        format_name = raw_params.pop(_FORMAT_QUERY_PARAM, default_format)
        if not _FORMAT_NAME_RE.fullmatch(format_name):
            return _error(400, "malformed format name")
        # Defense in depth: reject any variable-name key that would not
        # have passed the JSON Schema on declared variables. This keeps
        # attacker-controlled keys out of log lines and stops downstream
        # substitution helpers ever seeing them.
        for var_name in raw_params:
            if not _VARIABLE_NAME_RE.fullmatch(var_name):
                return _error(400, "malformed variable name")
        try:
            encoder = formats.get(format_name)
        except FormatNotFoundError:
            return _error(400, f"unknown format {format_name!r}")

        try:
            rendered = await engine.render(report_id, variables=raw_params)
        except ReportNotFoundError:
            return _error(404, f"report {report_id!r} not found")
        except VariableRejectedError as exc:
            return _error(400, str(exc))

        body = encoder.encode(rendered)
        headers = {}
        # Non-JSON formats download well as files - hint the FE / browser
        # so `curl -O`, "save as", and the console download button pick
        # a stable filename per (report_id, format).
        if format_name != "json":
            headers["Content-Disposition"] = f'attachment; filename="{report_id}.{format_name}"'
        _LOGGER.info(
            "reporting_rendered",
            extra={
                "actor": oid,
                "report_id": report_id,
                "format": format_name,
                "widget_count": len(rendered.widgets),
            },
        )
        return Response(body, media_type=encoder.content_type, headers=headers)

    return [
        Route(f"{prefix}", list_reports, methods=["GET"]),
        Route(f"{prefix}/registry", get_registry, methods=["GET"]),
        Route(f"{prefix}/formats", list_formats, methods=["GET"]),
        Route(f"{prefix}/widget-types", list_widget_types, methods=["GET"]),
        Route(f"{prefix}/datasources", list_datasource_names, methods=["GET"]),
        Route(f"{prefix}/health", get_health, methods=["GET"]),
        Route(
            f"{prefix}/{{report_id:str}}",
            get_report,
            methods=["GET"],
        ),
        Route(
            f"{prefix}/{{report_id:str}}/render",
            render_report,
            methods=["GET"],
        ),
    ]


def _summarize_spec(spec: ReportSpec) -> dict[str, Any]:
    return {
        "id": spec.id,
        "version": spec.version,
        "name": spec.name,
        "description": spec.description,
        "tags": list(spec.tags),
        "widget_count": _widget_count(spec.widgets),
        "variables": [
            {
                "name": v.name,
                "default": v.default,
                "values": list(v.values),
                "description": v.description,
            }
            for v in spec.variables
        ],
    }


def _full_spec_payload(spec: ReportSpec) -> dict[str, Any]:
    summary = _summarize_spec(spec)
    summary["time_range"] = _time_range_payload(spec)
    summary["widgets"] = [_widget_payload(w) for w in spec.widgets]
    return summary


def _time_range_payload(spec: ReportSpec) -> Mapping[str, Any]:
    tr = spec.time_range
    if tr.since is not None and tr.until is not None:
        return {"since": tr.since.isoformat(), "until": tr.until.isoformat()}
    if tr.since is not None:
        return {"since": tr.since.isoformat()}
    if tr.relative_duration is not None:
        return {"relative_duration_seconds": int(tr.relative_duration.total_seconds())}
    return {}


def _widget_payload(widget: WidgetSpec) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": widget.id,
        "type": widget.type,
        "title": widget.title,
        "options": dict(widget.options),
    }
    if widget.query is not None:
        payload["query"] = {
            "datasource": widget.query.datasource,
            "parameters": dict(widget.query.parameters),
        }
    if widget.children:
        payload["children"] = [_widget_payload(c) for c in widget.children]
    return payload


def _widget_count(widgets: tuple[WidgetSpec, ...]) -> int:
    total = 0
    for widget in widgets:
        total += 1
        if widget.children:
            total += _widget_count(widget.children)
    return total


def _error(status: int, message: str) -> Response:
    return JSONResponse({"error": message}, status_code=status)


__all__ = [
    "Authorize",
    "ReportingConfig",
    "build_reporting_routes",
]
