"""Authenticated cloud-knowledge projections and content-intake requests, never approval."""

from collections.abc import Callable
from uuid import UUID

from fdai_service_contracts.cloud_knowledge import canonical_bytes
from fdai_service_contracts.cloud_knowledge_package import MAX_PACKAGE_BYTES
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai_ingestion_api_service.auth import Principal, Role
from fdai_ingestion_api_service.cloud_knowledge.service import CloudKnowledgeService


def cloud_knowledge_routes(
    service: CloudKnowledgeService | None,
    authorize: Callable[[Request, tuple[Role, ...]], Principal],
) -> list[Route]:
    """Reuse the gateway's authentication; packages can never supply a reviewer identity."""
    readers = (Role.READER, Role.CONTRIBUTOR, Role.APPROVER, Role.OWNER)
    writers = (Role.CONTRIBUTOR, Role.APPROVER, Role.OWNER)

    def resolve() -> CloudKnowledgeService:
        if service is None:
            raise ValueError("cloud knowledge requires approved source and trust configuration")
        return service

    def groups(principal: Principal) -> frozenset[str]:
        return principal.groups | frozenset(f"role:{role.value}" for role in principal.roles)

    async def status(request: Request) -> Response:
        principal = authorize(request, readers)
        if service is None:
            return JSONResponse(
                {
                    "available": False,
                    "reason": "source_and_trust_policy_required",
                    "sources": [],
                    "collections": [],
                    "can_refresh": False,
                    "can_import": False,
                }
            )
        payload = await service.status(actor_id=principal.oid, actor_groups=groups(principal))
        return JSONResponse(
            {
                **payload,
                "can_refresh": Role.OWNER in principal.roles
                and payload.get("policy_current") is True,
                "can_import": bool(principal.roles.intersection(writers))
                and payload.get("policy_current") is True,
            }
        )

    async def refresh(request: Request) -> Response:
        authorize(request, (Role.OWNER,))
        return JSONResponse(await resolve().refresh())

    async def export(request: Request) -> Response:
        authorize(request, (Role.OWNER,))
        manifest = await resolve().proposal(request.path_params["collection_id"])
        return Response(
            canonical_bytes(manifest),
            media_type="application/json",
            headers={
                "content-disposition": 'attachment; filename="cloud-knowledge-review.json"',
                "cache-control": "no-store",
                "x-content-type-options": "nosniff",
            },
        )

    async def stage(request: Request) -> Response:
        principal = authorize(request, writers)
        return JSONResponse(
            await resolve().stage_collected(
                collection_id=request.path_params["collection_id"],
                actor_id=principal.oid,
                actor_groups=groups(principal),
            ),
            status_code=202,
        )

    async def rollback(request: Request) -> Response:
        principal = authorize(request, (Role.OWNER,))
        return JSONResponse(
            await resolve().rollback(
                collection_id=request.path_params["collection_id"],
                version_id=UUID(request.path_params["version_id"]),
                actor_id=principal.oid,
                actor_groups=groups(principal),
            ),
            status_code=202,
        )

    async def package(request: Request) -> Response:
        principal = authorize(request, writers)
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > MAX_PACKAGE_BYTES:
                raise ValueError("knowledge package exceeds the byte limit")
            content.extend(chunk)
        if request.url.path.endswith("/inspect"):
            return JSONResponse(resolve().inspect(bytes(content)))
        return JSONResponse(
            await resolve().import_package(
                bytes(content), actor_id=principal.oid, actor_groups=groups(principal)
            ),
            status_code=202,
        )

    return [
        Route("/ingestion/cloud-knowledge", status, methods=["GET"]),
        Route("/ingestion/cloud-knowledge/refresh", refresh, methods=["POST"]),
        Route("/ingestion/cloud-knowledge/{collection_id}/export", export, methods=["POST"]),
        Route("/ingestion/cloud-knowledge/{collection_id}/stage", stage, methods=["POST"]),
        Route(
            "/ingestion/cloud-knowledge/{collection_id}/versions/{version_id}/rollback",
            rollback,
            methods=["POST"],
        ),
        Route("/ingestion/cloud-knowledge/packages/inspect", package, methods=["POST"]),
        Route("/ingestion/cloud-knowledge/packages/import", package, methods=["POST"]),
    ]
