"""Authenticated configuration trust routes; loopback identity strings cannot approve keys."""

from __future__ import annotations

from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai_lifecycle_hub.configuration_key_store import ConfigurationKeyStore
from fdai_lifecycle_hub.configuration_keys import KeyBindingError, KeyDecision, SignedKeyRequest
from fdai_lifecycle_hub.domain import Clock


def key_routes(store: ConfigurationKeyStore, clock: Clock, *, authenticated: bool) -> list[Route]:
    async def change(request: Request) -> Response:
        from fdai_lifecycle_hub.api import _read_limited

        if not authenticated or not getattr(request.state, "operator", None):
            return JSONResponse({"error": "authenticated_operator_required"}, status_code=403)
        installation_id = request.path_params["installation_id"]
        actor = request.state.operator
        operation = request.path_params["operation"]
        raw = await _read_limited(request, 8192)
        if raw is None:
            try:
                await run_in_threadpool(
                    store.deny,
                    installation_id,
                    actor=actor,
                    now=clock(),
                    reason="configuration_request_too_large",
                )
            except KeyBindingError:
                pass
            return JSONResponse({"error": "configuration_request_too_large"}, status_code=413)
        try:
            if operation == "request":
                digest = await run_in_threadpool(
                    store.request,
                    installation_id,
                    SignedKeyRequest.model_validate_json(raw),
                    actor=actor,
                    now=clock(),
                )
            elif operation in {"approve", "revoke"}:
                decision = KeyDecision.model_validate_json(raw)
                method = store.approve if operation == "approve" else store.revoke
                digest = await run_in_threadpool(
                    method, installation_id, decision.request_digest, actor=actor, now=clock()
                )
            else:
                return JSONResponse({"error": "not_found"}, status_code=404)
        except ValidationError:
            try:
                await run_in_threadpool(
                    store.deny,
                    installation_id,
                    actor=actor,
                    now=clock(),
                    reason="configuration_request_invalid",
                )
            except KeyBindingError:
                pass
            return JSONResponse({"error": "configuration_request_invalid"}, status_code=422)
        except KeyBindingError as error:
            return JSONResponse({"error": str(error)}, status_code=409)
        return JSONResponse({"request_digest": digest}, status_code=202)

    async def status(request: Request) -> Response:
        if not authenticated:
            return JSONResponse({"error": "authenticated_operator_required"}, status_code=403)
        return JSONResponse(
            await run_in_threadpool(store.status, request.path_params["installation_id"])
        )

    async def pending(request: Request) -> Response:
        if not authenticated:
            return JSONResponse({"error": "authenticated_operator_required"}, status_code=403)
        try:
            result = await run_in_threadpool(
                store.pending_request,
                request.path_params["installation_id"],
                request.path_params["digest"],
            )
        except KeyBindingError as error:
            return JSONResponse({"error": str(error)}, status_code=404)
        return JSONResponse(result)

    return [
        Route("/v1/installations/{installation_id}/configuration-keys", status),
        Route(
            "/v1/installations/{installation_id}/configuration-keys/requests/{digest}",
            pending,
        ),
        Route(
            "/v1/installations/{installation_id}/configuration-keys/{operation}",
            change,
            methods=["POST"],
        ),
    ]
