"""Authenticated scheduling changes never compute or approve an execution Plan."""

from __future__ import annotations

from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai_lifecycle_hub.domain import Clock
from fdai_lifecycle_hub.execution_settings import ExecutionSettingsError, ExecutionSettingsRequest
from fdai_lifecycle_hub.store import HubStore


def execution_settings_routes(store: HubStore, clock: Clock, *, authenticated: bool) -> list[Route]:
    async def endpoint(request: Request) -> Response:
        from fdai_lifecycle_hub.api import _read_limited

        if not authenticated or not getattr(request.state, "operator", None):
            return JSONResponse({"error": "authenticated_operator_required"}, status_code=403)
        installation_id = request.path_params["installation_id"]
        if request.method == "GET":
            return JSONResponse(await run_in_threadpool(store.execution_settings, installation_id))
        raw = await _read_limited(request, 8192)
        if raw is None:
            return JSONResponse({"error": "execution_settings_too_large"}, status_code=413)
        try:
            command = ExecutionSettingsRequest.model_validate_json(raw)
        except ValidationError:
            return JSONResponse({"error": "execution_settings_invalid"}, status_code=422)
        try:
            result = await run_in_threadpool(
                store.update_execution_settings,
                installation_id,
                command,
                operator=request.state.operator,
                now=clock(),
            )
        except ExecutionSettingsError as error:
            return JSONResponse({"error": str(error)}, status_code=409)
        return JSONResponse(result)

    return [
        Route(
            "/v1/installations/{installation_id}/execution-settings",
            endpoint,
            methods=["GET", "POST"],
        )
    ]
