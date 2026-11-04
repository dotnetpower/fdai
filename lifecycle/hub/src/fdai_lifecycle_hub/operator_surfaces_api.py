"""HTTP routes for Lifecycle Hub commands, destructive confirmations, and bundle imports."""

from __future__ import annotations

from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai_lifecycle_hub.domain import Clock
from fdai_lifecycle_hub.operator_surfaces import (
    BundleImportError,
    BundleImportRequest,
    DecideDestructiveConfirmationRequest,
    IssueLifecycleCommandRequest,
    LifecycleCommandError,
    ProposeDestructiveConfirmationRequest,
)
from fdai_lifecycle_hub.store import HubStore

MAX_SURFACE_BODY_BYTES = 16 * 1024


def operator_surface_routes(store: HubStore, clock: Clock) -> list[Route]:
    """Build operator routes for commands, exact-plan confirmations, and bundle import."""

    def _operator_actor(request: Request) -> str:
        operator = getattr(request.state, "operator", None)
        return operator if isinstance(operator, str) and operator.strip() else "local-operator"

    async def get_commands(request: Request) -> Response:
        installation_id = request.query_params.get("installation_id")
        records = await run_in_threadpool(
            store.list_lifecycle_commands,
            installation_id=installation_id if installation_id else None,
            now=clock(),
        )
        return JSONResponse({"commands": records})

    async def post_command(request: Request) -> Response:
        from fdai_lifecycle_hub.api import _decision_request_error, _error, _read_limited

        if error := _decision_request_error(request):
            return error
        body = await _read_limited(request, MAX_SURFACE_BODY_BYTES)
        if body is None:
            return _error(413, "request_too_large")
        try:
            command_req = IssueLifecycleCommandRequest.model_validate_json(body)
        except ValidationError:
            return _error(422, "command_invalid")
        installation_id = request.path_params["installation_id"]
        try:
            record = await run_in_threadpool(
                store.issue_lifecycle_command,
                installation_id,
                command_req,
                operator=_operator_actor(request),
                now=clock(),
            )
        except LifecycleCommandError as exc:
            return _error(422, exc.reason_code)
        return JSONResponse(record, status_code=201)

    async def get_confirmations(request: Request) -> Response:
        records = await run_in_threadpool(store.list_destructive_confirmations)
        return JSONResponse({"confirmations": records})

    async def post_confirmation_proposal(request: Request) -> Response:
        from fdai_lifecycle_hub.api import _decision_request_error, _error, _read_limited

        if error := _decision_request_error(request):
            return error
        body = await _read_limited(request, MAX_SURFACE_BODY_BYTES)
        if body is None:
            return _error(413, "request_too_large")
        try:
            proposal = ProposeDestructiveConfirmationRequest.model_validate_json(body)
        except ValidationError:
            return _error(422, "confirmation_invalid")
        installation_id = request.path_params["installation_id"]
        plan_id = request.path_params["plan_id"]
        try:
            record = await run_in_threadpool(
                store.propose_destructive_confirmation,
                installation_id,
                plan_id,
                proposal,
                now=clock(),
            )
        except LifecycleCommandError as exc:
            return _error(422, exc.reason_code)
        return JSONResponse(record, status_code=201)

    async def post_confirmation_decision(request: Request) -> Response:
        from fdai_lifecycle_hub.api import _decision_request_error, _error, _read_limited

        if error := _decision_request_error(request):
            return error
        body = await _read_limited(request, MAX_SURFACE_BODY_BYTES)
        if body is None:
            return _error(413, "request_too_large")
        try:
            decision = DecideDestructiveConfirmationRequest.model_validate_json(body)
        except ValidationError:
            return _error(422, "confirmation_invalid")
        installation_id = request.path_params["installation_id"]
        plan_id = request.path_params["plan_id"]
        try:
            record = await run_in_threadpool(
                store.decide_destructive_confirmation,
                installation_id,
                plan_id,
                decision,
                operator=_operator_actor(request),
                now=clock(),
            )
        except LifecycleCommandError as exc:
            return _error(422, exc.reason_code)
        return JSONResponse(record)

    async def get_bundle_imports(request: Request) -> Response:
        payload = await run_in_threadpool(store.list_bundle_imports)
        return JSONResponse(payload)

    async def post_bundle_import(request: Request) -> Response:
        from fdai_lifecycle_hub.api import _decision_request_error, _error, _read_limited

        if error := _decision_request_error(request):
            return error
        body = await _read_limited(request, MAX_SURFACE_BODY_BYTES)
        if body is None:
            return _error(413, "request_too_large")
        try:
            bundle_req = BundleImportRequest.model_validate_json(body)
        except ValidationError:
            return _error(422, "bundle_import_invalid")
        try:
            record = await run_in_threadpool(
                store.import_upgrade_bundle,
                bundle_req,
                operator=_operator_actor(request),
                now=clock(),
            )
        except BundleImportError as exc:
            return _error(422, exc.reason_code)
        return JSONResponse(record, status_code=201)

    return [
        Route("/v1/commands", get_commands, methods=["GET"]),
        Route(
            "/v1/installations/{installation_id}/commands",
            post_command,
            methods=["POST"],
        ),
        Route("/v1/confirmations", get_confirmations, methods=["GET"]),
        Route(
            "/v1/installations/{installation_id}/plans/{plan_id}/confirmations",
            post_confirmation_proposal,
            methods=["POST"],
        ),
        Route(
            "/v1/installations/{installation_id}/plans/{plan_id}/confirmations/decision",
            post_confirmation_decision,
            methods=["POST"],
        ),
        Route("/v1/bundle-imports", get_bundle_imports, methods=["GET"]),
        Route("/v1/bundle-imports", post_bundle_import, methods=["POST"]),
    ]
