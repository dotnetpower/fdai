"""Starlette boundary for document upload and lifecycle operations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.document_ingestion import (
    CreateUploadRequest,
    DocumentIngestionService,
    DocumentIngestionWorker,
)
from fdai.core.rbac.enforcer import RoleRequiredError
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.delivery.read_api.auth import AuthenticationError, Authenticator
from fdai.shared.contracts import DocumentPurpose, DocumentState, SourceStorageMode
from fdai.shared.providers import (
    DocumentAccessDeniedError,
    DocumentNotFoundError,
    ProviderUnavailableError,
)

_DEV_MODE_ENV = "FDAI_INGESTION_GATEWAY_DEV_MODE"
_READER_ROLES = (Role.READER, Role.CONTRIBUTOR, Role.APPROVER, Role.OWNER)
_CONTRIBUTOR_ROLES = (Role.CONTRIBUTOR, Role.APPROVER, Role.OWNER)


@dataclass(frozen=True, slots=True)
class IngestionGatewayConfig:
    dev_mode: bool = False
    direct_upload: bool = False
    cors_allow_origins: tuple[str, ...] = ()


def build_app(
    *,
    authenticator: Authenticator,
    service: DocumentIngestionService,
    worker: DocumentIngestionWorker,
    config: IngestionGatewayConfig | None = None,
) -> Starlette:
    resolved = config or IngestionGatewayConfig()
    _validate_boundary(resolved)

    def authorize(request: Request, roles: tuple[Role, ...]) -> Principal:
        if resolved.dev_mode:
            return Principal(oid="ingestion-dev", roles=frozenset({Role.OWNER}))
        return authenticator.require_roles(request.headers.get("authorization"), required=roles)

    async def capabilities(request: Request) -> Response:
        authorize(request, _READER_ROLES)
        payload = service.capabilities.model_copy(
            update={"direct_upload": resolved.dev_mode and resolved.direct_upload}
        )
        return _json(payload)

    async def create_upload(request: Request) -> Response:
        principal = authorize(request, _CONTRIBUTOR_ROLES)
        body = await _json_body(request)
        upload_request = _create_request(body)
        session, grant = await service.create_upload(actor_id=principal.oid, request=upload_request)
        target = grant.target
        if resolved.dev_mode and resolved.direct_upload:
            target = f"/ingestion/uploads/{session.upload_id}/content"
        return JSONResponse(
            {
                "session": session.model_dump(mode="json"),
                "upload": {
                    "target": target,
                    "expires_at": grant.expires_at.isoformat(),
                    "completed_parts": list(grant.completed_parts),
                },
            },
            status_code=201,
        )

    async def resume_upload(request: Request) -> Response:
        principal = authorize(request, _CONTRIBUTOR_ROLES)
        upload_id = _uuid(request.path_params["upload_id"], "upload_id")
        grant = await service.resume_upload(actor_id=principal.oid, upload_id=upload_id)
        target = grant.target
        if resolved.dev_mode and resolved.direct_upload:
            target = f"/ingestion/uploads/{upload_id}/content"
        return JSONResponse(
            {
                "target": target,
                "expires_at": grant.expires_at.isoformat(),
                "completed_parts": list(grant.completed_parts),
            }
        )

    async def put_content(request: Request) -> Response:
        if not (resolved.dev_mode and resolved.direct_upload):
            return _error(404, "not_found", "direct upload is unavailable")
        principal = authorize(request, _CONTRIBUTOR_ROLES)
        upload_id = _uuid(request.path_params["upload_id"], "upload_id")
        content = await _bounded_body(request, service.capabilities.max_file_size)
        await service.put_local_content(
            actor_id=principal.oid, upload_id=upload_id, content=content
        )
        return Response(status_code=204)

    async def complete_upload(request: Request) -> Response:
        principal = authorize(request, _CONTRIBUTOR_ROLES)
        upload_id = _uuid(request.path_params["upload_id"], "upload_id")
        session = await service.complete_upload(actor_id=principal.oid, upload_id=upload_id)
        return _json(session, status_code=202)

    async def upload_status(request: Request) -> Response:
        principal = authorize(request, _READER_ROLES)
        upload_id = _uuid(request.path_params["upload_id"], "upload_id")
        session = await service.get_upload(actor_id=principal.oid, upload_id=upload_id)
        return _json(session)

    async def cancel_upload(request: Request) -> Response:
        principal = authorize(request, _CONTRIBUTOR_ROLES)
        upload_id = _uuid(request.path_params["upload_id"], "upload_id")
        session = await service.get_upload(actor_id=principal.oid, upload_id=upload_id)
        if session.state in {
            DocumentState.CREATED,
            DocumentState.UPLOADING,
            DocumentState.RECEIVED,
        }:
            cancelled = await service.cancel_upload(actor_id=principal.oid, upload_id=upload_id)
            return _json(cancelled, status_code=202)
        deleted = await worker.delete(
            actor_id=principal.oid,
            document_id=session.document_id,
            version_id=session.version_id,
        )
        return _json(deleted, status_code=202)

    async def versions(request: Request) -> Response:
        principal = authorize(request, _READER_ROLES)
        document_id = _uuid(request.path_params["document_id"], "document_id")
        items = await service.list_versions(actor_id=principal.oid, document_id=document_id)
        return JSONResponse({"items": [item.model_dump(mode="json") for item in items]})

    async def delete_version(request: Request) -> Response:
        principal = authorize(request, _CONTRIBUTOR_ROLES)
        document_id = _uuid(request.path_params["document_id"], "document_id")
        version_id = _uuid(request.path_params["version_id"], "version_id")
        version = await worker.delete(
            actor_id=principal.oid, document_id=document_id, version_id=version_id
        )
        return _json(version, status_code=202)

    routes = [
        Route("/ingestion/capabilities", capabilities, methods=["GET"]),
        Route("/ingestion/uploads", create_upload, methods=["POST"]),
        Route("/ingestion/uploads/{upload_id}/resume", resume_upload, methods=["POST"]),
        Route("/ingestion/uploads/{upload_id}/content", put_content, methods=["PUT"]),
        Route("/ingestion/uploads/{upload_id}/complete", complete_upload, methods=["POST"]),
        Route("/ingestion/uploads/{upload_id}", upload_status, methods=["GET"]),
        Route("/ingestion/uploads/{upload_id}/cancel", cancel_upload, methods=["POST"]),
        Route("/documents/{document_id}/versions", versions, methods=["GET"]),
        Route(
            "/documents/{document_id}/versions/{version_id}",
            delete_version,
            methods=["DELETE"],
        ),
    ]
    middleware: list[Middleware] = []
    if resolved.cors_allow_origins:
        middleware.append(
            Middleware(
                CORSMiddleware,
                allow_origins=list(resolved.cors_allow_origins),
                allow_methods=["GET", "POST", "PUT", "DELETE"],
                allow_headers=["authorization", "content-type"],
                allow_credentials=False,
            )
        )

    async def authentication_error(_request: Request, _exc: Exception) -> Response:
        return _error(401, "unauthorized", "authentication is required")

    async def authorization_error(_request: Request, _exc: Exception) -> Response:
        return _error(403, "forbidden", "document access is denied")

    async def not_found(_request: Request, _exc: Exception) -> Response:
        return _error(404, "not_found", "document resource was not found")

    async def unavailable(_request: Request, _exc: Exception) -> Response:
        return _error(503, "provider_unavailable", "a required safety provider is unavailable")

    async def bad_request(_request: Request, exc: Exception) -> Response:
        return _error(400, "invalid_request", str(exc))

    return Starlette(
        routes=routes,
        middleware=middleware,
        exception_handlers={
            AuthenticationError: authentication_error,
            RoleRequiredError: authorization_error,
            DocumentAccessDeniedError: authorization_error,
            DocumentNotFoundError: not_found,
            ProviderUnavailableError: unavailable,
            ValueError: bad_request,
            ValidationError: bad_request,
        },
    )


def _validate_boundary(config: IngestionGatewayConfig) -> None:
    runtime_env = os.environ.get("RUNTIME_ENV", "").strip().lower()
    if config.dev_mode and os.environ.get(_DEV_MODE_ENV) != "1":
        raise ValueError(f"dev_mode requires {_DEV_MODE_ENV}=1")
    if config.dev_mode and runtime_env in {"staging", "prod"}:
        raise ValueError("ingestion dev mode is prohibited outside a local environment")
    if config.direct_upload and not config.dev_mode:
        raise ValueError("direct gateway upload is available only in explicit dev mode")
    if "*" in config.cors_allow_origins and not config.dev_mode:
        raise ValueError("wildcard CORS is prohibited outside dev mode")


def _create_request(body: dict[str, Any]) -> CreateUploadRequest:
    required = {
        "source_name",
        "collection_id",
        "media_type_hint",
        "expected_size",
        "expected_sha256",
        "storage_mode",
        "purposes",
        "access_descriptor_ref",
        "retention_policy_version",
    }
    missing = sorted(required - body.keys())
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")
    allowed = required | {"reader_groups", "document_id", "supersedes_version_id"}
    unknown = sorted(body.keys() - allowed)
    if unknown:
        raise ValueError(f"unknown fields: {', '.join(unknown)}")
    return CreateUploadRequest(
        source_name=str(body["source_name"]),
        collection_id=str(body["collection_id"]),
        media_type_hint=str(body["media_type_hint"]),
        expected_size=int(body["expected_size"]),
        expected_sha256=str(body["expected_sha256"]),
        storage_mode=SourceStorageMode(str(body["storage_mode"])),
        purposes=tuple(DocumentPurpose(str(value)) for value in body["purposes"]),
        access_descriptor_ref=str(body["access_descriptor_ref"]),
        reader_groups=tuple(str(value) for value in body.get("reader_groups", ())),
        retention_policy_version=str(body["retention_policy_version"]),
        document_id=_optional_uuid(body.get("document_id"), "document_id"),
        supersedes_version_id=_optional_uuid(
            body.get("supersedes_version_id"), "supersedes_version_id"
        ),
    )


async def _json_body(request: Request) -> dict[str, Any]:
    value = await request.json()
    if not isinstance(value, dict):
        raise ValueError("request body MUST be a JSON object")
    return value


async def _bounded_body(request: Request, limit: int) -> bytes:
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > limit:
            raise ValueError("request body exceeds the advertised file-size limit")
    return bytes(content)


def _uuid(value: str, field: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise ValueError(f"{field} MUST be a UUID") from exc


def _optional_uuid(value: object, field: str) -> UUID | None:
    if value is None:
        return None
    return _uuid(str(value), field)


def _json(model: Any, *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(model.model_dump(mode="json"), status_code=status_code)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": code, "message": message}, status_code=status)


__all__ = ["IngestionGatewayConfig", "build_app"]
