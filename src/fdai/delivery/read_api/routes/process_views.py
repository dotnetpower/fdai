"""Read-only dynamic process-view listing and render routes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.views import ProcessViewLookupError, ViewEngine, WorkflowAppManifest
from fdai.shared.providers.process_runtime import PROCESS_ID_PATTERN, ProcessStatus

DEFAULT_ROUTE_PREFIX = "/views/process"
DEFAULT_WORKFLOW_APPS_PREFIX = "/views/workflow-apps"


@dataclass(frozen=True, slots=True)
class ProcessViewsConfig:
    engine: ViewEngine
    prefix: str = DEFAULT_ROUTE_PREFIX
    apps_prefix: str = DEFAULT_WORKFLOW_APPS_PREFIX
    apps: tuple[WorkflowAppManifest, ...] = ()
    source: str = "unknown"
    synthetic: bool | None = None
    durable: bool | None = None


def build_process_view_routes(
    *,
    config: ProcessViewsConfig,
    authorize: Callable[[Request], Awaitable[str]],
    core_paths: frozenset[str] | None = None,
    seen_extra_paths: set[str] | None = None,
) -> list[Route]:
    prefix = config.prefix.rstrip("/") or DEFAULT_ROUTE_PREFIX
    apps_prefix = config.apps_prefix.rstrip("/") or DEFAULT_WORKFLOW_APPS_PREFIX
    if not prefix.startswith("/"):
        raise ValueError("process view prefix MUST start with '/'")
    if not apps_prefix.startswith("/"):
        raise ValueError("workflow apps prefix MUST start with '/'")
    if prefix == apps_prefix:
        raise ValueError("process view and workflow apps routes MUST be distinct")
    if core_paths is not None:
        for path in (prefix, apps_prefix):
            if path in core_paths:
                raise ValueError(f"process view route {path!r} collides with a core route")
    if seen_extra_paths is not None:
        for path in (prefix, apps_prefix):
            if path in seen_extra_paths:
                raise ValueError(f"process view route {path!r} collides with an extra route")
            seen_extra_paths.add(path)

    async def list_workflow_apps(request: Request) -> Response:
        await authorize(request)
        items = [app.to_dict() for app in config.apps if app.is_hub_visible]
        return JSONResponse({"items": items, "count": len(items)})

    async def list_processes(request: Request) -> Response:
        await authorize(request)
        workflow_ref = request.query_params.get("workflow_ref") or None
        raw_status = request.query_params.get("status")
        try:
            status = ProcessStatus(raw_status) if raw_status else None
            limit = int(request.query_params.get("limit", "100"))
            items = await config.engine.list_processes(
                workflow_ref=workflow_ref,
                status=status,
                limit=limit,
            )
        except (ValueError, TypeError) as exc:
            return _error(400, str(exc))
        return JSONResponse(
            {
                "source": config.source,
                "synthetic": config.synthetic,
                "durable": config.durable,
                "items": list(items),
            }
        )

    async def render_process(request: Request) -> Response:
        await authorize(request)
        process_id = request.path_params["process_id"]
        if not PROCESS_ID_PATTERN.fullmatch(process_id):
            return _error(400, "malformed process id")
        try:
            rendered = await config.engine.render_process(process_id)
        except ProcessViewLookupError as exc:
            return _error(404, str(exc))
        return JSONResponse(rendered.to_dict())

    async def process_events(request: Request) -> Response:
        await authorize(request)
        process_id = request.path_params["process_id"]
        if not PROCESS_ID_PATTERN.fullmatch(process_id):
            return _error(400, "malformed process id")
        try:
            journal = await config.engine.process_journal(process_id)
        except ProcessViewLookupError as exc:
            return _error(404, str(exc))
        return JSONResponse(journal)

    return [
        Route(apps_prefix, list_workflow_apps, methods=["GET"]),
        Route(prefix, list_processes, methods=["GET"]),
        Route(f"{prefix}/{{process_id:str}}", render_process, methods=["GET"]),
        Route(f"{prefix}/{{process_id:str}}/events", process_events, methods=["GET"]),
    ]


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": {"status": status, "message": message}}, status_code=status)


__all__ = [
    "DEFAULT_ROUTE_PREFIX",
    "DEFAULT_WORKFLOW_APPS_PREFIX",
    "ProcessViewsConfig",
    "build_process_view_routes",
]
