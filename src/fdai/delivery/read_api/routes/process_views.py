"""Read-only dynamic process-view listing and render routes."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.views import ViewEngine
from fdai.shared.providers.process_runtime import ProcessStatus

DEFAULT_ROUTE_PREFIX = "/views/process"
_PROCESS_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")


@dataclass(frozen=True, slots=True)
class ProcessViewsConfig:
    engine: ViewEngine
    prefix: str = DEFAULT_ROUTE_PREFIX


def build_process_view_routes(
    *,
    config: ProcessViewsConfig,
    authorize: Callable[[Request], Awaitable[str]],
) -> list[Route]:
    prefix = config.prefix.rstrip("/") or DEFAULT_ROUTE_PREFIX
    if not prefix.startswith("/"):
        raise ValueError("process view prefix MUST start with '/'")

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
        return JSONResponse({"items": list(items)})

    async def render_process(request: Request) -> Response:
        await authorize(request)
        process_id = request.path_params["process_id"]
        if not _PROCESS_ID_RE.fullmatch(process_id):
            return _error(400, "malformed process id")
        try:
            rendered = await config.engine.render_process(process_id)
        except KeyError as exc:
            return _error(404, str(exc))
        return JSONResponse(rendered.to_dict())

    return [
        Route(prefix, list_processes, methods=["GET"]),
        Route(f"{prefix}/{{process_id:str}}", render_process, methods=["GET"]),
    ]


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": {"status": status, "message": message}}, status_code=status)


__all__ = ["DEFAULT_ROUTE_PREFIX", "ProcessViewsConfig", "build_process_view_routes"]
