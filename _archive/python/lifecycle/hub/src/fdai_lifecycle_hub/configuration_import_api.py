"""JWT operator-only bounded signed import; no package key or actor creates authority."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy.engine import Connection
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai_lifecycle_hub.catalog import ReleaseCatalog
from fdai_lifecycle_hub.configuration_import_contracts import (
    ImportDecision,
    ScopeDecision,
    SignedImportRequest,
    SignedScopeRequest,
)
from fdai_lifecycle_hub.configuration_import_store import ConfigurationImportStore
from fdai_lifecycle_hub.configuration_key_store import DevelopmentRecoveryAuthorizationLike
from fdai_lifecycle_hub.configuration_keys import KeyBindingError
from fdai_lifecycle_hub.domain import Clock
from fdai_lifecycle_hub.remote_catalog import RemoteCatalog


def configuration_routes(
    store: ConfigurationImportStore,
    catalog: RemoteCatalog,
    clock: Clock,
    *,
    recovery_authorization: DevelopmentRecoveryAuthorizationLike | None = None,
) -> list[Route]:
    async def change(request: Request) -> Response:
        from fdai_lifecycle_hub.api import _read_limited

        actor = getattr(request.state, "operator", None)
        if not actor:
            return JSONResponse({"error": "authenticated_operator_required"}, status_code=403)
        installation_id = request.path_params["installation_id"]
        operation = request.path_params["operation"]
        scope_operation = "/configuration-scope/" in request.url.path
        limit = 65536 if scope_operation else 4 * 1024 * 1024 + 65536
        raw = await _read_limited(request, limit)
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
            if scope_operation and operation == "request":
                value: SignedScopeRequest | SignedImportRequest | ScopeDecision | ImportDecision
                value = SignedScopeRequest.model_validate_json(raw)
            elif scope_operation and operation == "approve":
                value = ScopeDecision.model_validate_json(raw)
            elif not scope_operation and operation == "import":
                value = SignedImportRequest.model_validate_json(raw)
            elif not scope_operation and operation in {"approve", "activate"}:
                value = ImportDecision.model_validate_json(raw)
            else:
                return JSONResponse({"error": "not_found"}, status_code=404)

            def execute(
                admitted: ReleaseCatalog, now: datetime, connection: Connection
            ) -> dict[str, Any]:
                bound = ConfigurationImportStore(connection)
                if isinstance(value, SignedImportRequest):
                    return bound.import_revision(
                        installation_id, value, actor=actor, now=now, catalog=admitted
                    )
                if isinstance(value, SignedScopeRequest):
                    return bound.request_scope(
                        installation_id, value, actor=actor, now=now, catalog=admitted
                    )
                if isinstance(value, ScopeDecision):
                    return bound.approve_scope(
                        installation_id,
                        value.digest,
                        actor=actor,
                        now=now,
                        catalog=admitted,
                        recovery_authorization=recovery_authorization,
                    )
                method = bound.approve_change if operation == "approve" else bound.activate
                return method(
                    installation_id,
                    value,
                    actor=actor,
                    now=now,
                    catalog=admitted,
                    recovery_authorization=recovery_authorization,
                )

            result = await run_in_threadpool(catalog.configuration_operation, execute, now=clock())
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
        except ValueError as error:
            reason = (
                str(error)
                if isinstance(error, KeyBindingError)
                else "configuration_trust_unavailable"
            )
            return JSONResponse({"error": reason}, status_code=409)
        return JSONResponse(result, status_code=202)

    async def read(request: Request) -> Response:
        if not getattr(request.state, "operator", None):
            return JSONResponse({"error": "authenticated_operator_required"}, status_code=403)
        try:
            if "/configuration-scope/" in request.url.path:
                result = await run_in_threadpool(
                    store.read_scope,
                    request.path_params["installation_id"],
                    request.path_params["digest"],
                )
            else:
                result = await run_in_threadpool(
                    store.read,
                    request.path_params["installation_id"],
                    request.path_params.get("digest"),
                )
        except KeyBindingError as error:
            return JSONResponse({"error": str(error)}, status_code=404)
        return JSONResponse(result)

    root = "/v1/installations/{installation_id}"
    return [
        Route(root + "/configuration", read),
        Route(root + "/configuration/revisions/{digest}", read),
        Route(root + "/configuration-scope/requests/{digest}", read),
        Route(root + "/configuration/{operation}", change, methods=["POST"]),
        Route(root + "/configuration-scope/{operation}", change, methods=["POST"]),
    ]
