"""Native creation cannot self-authorize through an Agent identity."""

from __future__ import annotations

from fdai_deployment_cli.contracts import load_json_object
from fdai_deployment_cli.lifecycle_native import NativeOwnershipAcceptance
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai_lifecycle_hub.domain import Clock
from fdai_lifecycle_hub.native_ownership import NativeOwnershipError, NativeOwnershipStore
from fdai_lifecycle_hub.store import HubStore


def native_ownership_routes(store: HubStore, clock: Clock, *, authenticated: bool) -> list[Route]:
    async def accept(request: Request) -> Response:
        from fdai_lifecycle_hub.api import _read_limited

        if not authenticated or not getattr(request.state, "operator", None):
            return JSONResponse({"error": "authenticated_operator_required"}, status_code=403)
        body = await _read_limited(request, 8192)
        if body is None:
            return JSONResponse({"error": "native_ownership_too_large"}, status_code=413)
        try:
            load_json_object(body, label="native ownership", max_bytes=8192, strict=True)
            command = NativeOwnershipAcceptance.model_validate_json(body)
        except ValueError:
            return JSONResponse({"error": "native_ownership_invalid"}, status_code=422)
        try:
            result = await run_in_threadpool(
                NativeOwnershipStore(store).accept,
                request.path_params["installation_id"],
                command,
                operator=request.state.operator,
                now=clock(),
            )
        except NativeOwnershipError as error:
            return JSONResponse({"error": str(error)}, status_code=409)
        return JSONResponse(result)

    return [
        Route(
            "/v1/installations/{installation_id}/native-ownership",
            accept,
            methods=["POST"],
        )
    ]
