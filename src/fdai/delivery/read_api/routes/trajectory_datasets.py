"""Read-only, purpose-limited trajectory dataset metadata routes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.core.trajectory import TrajectoryDatasetAdminService, TrajectoryDatasetQuery
from fdai.shared.providers.trajectory import TrajectoryDatasetRecord

AuthorizePrincipal = Callable[[Request], Awaitable[Principal]]


def make_trajectory_dataset_routes(
    *,
    service: TrajectoryDatasetAdminService,
    authorize_principal: AuthorizePrincipal,
) -> tuple[Route, ...]:
    async def list_datasets(request: Request) -> Response:
        principal = await _owner(request, authorize_principal)
        query = _query(request, principal)
        try:
            records = await service.list(query)
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail="trajectory dataset not found") from exc
        return JSONResponse(
            {
                "read_only": True,
                "datasets": [_record(item) for item in records],
                "training_actions_available": False,
                "promotion_actions_available": False,
            }
        )

    async def get_dataset(request: Request) -> Response:
        principal = await _owner(request, authorize_principal)
        query = _query(request, principal)
        try:
            record = await service.get(
                dataset_id=request.path_params["dataset_id"],
                principal_id=principal.oid,
                access_scope=query.access_scope,
                purpose=query.purpose,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail="trajectory dataset not found") from exc
        if record is None:
            raise HTTPException(status_code=404, detail="trajectory dataset not found")
        return JSONResponse(
            {
                "read_only": True,
                "dataset": _record(record),
                "training_actions_available": False,
                "promotion_actions_available": False,
            }
        )

    return (
        Route("/admin/trajectory-datasets", list_datasets, methods=["GET"]),
        Route("/admin/trajectory-datasets/{dataset_id}", get_dataset, methods=["GET"]),
    )


async def _owner(request: Request, authorize: AuthorizePrincipal) -> Principal:
    principal = await authorize(request)
    if Role.OWNER not in principal.roles:
        raise HTTPException(status_code=403, detail="Owner role is required")
    return principal


def _query(request: Request, principal: Principal) -> TrajectoryDatasetQuery:
    purpose = request.query_params.get("purpose", "").strip()
    access_scope = request.query_params.get("access_scope", "").strip()
    if not purpose or not access_scope:
        raise HTTPException(status_code=400, detail="purpose and access_scope are required")
    try:
        limit = int(request.query_params.get("limit", "100"))
        return TrajectoryDatasetQuery(
            principal_id=principal.oid,
            access_scope=access_scope,
            purpose=purpose,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _record(record: TrajectoryDatasetRecord) -> dict[str, object]:
    return {
        "dataset_id": record.dataset_id,
        "purpose": record.purpose,
        "principal_scope_digest": record.principal_scope_digest,
        "state": record.state.value,
        "schema_version": record.schema_version,
        "record_count": record.record_count,
        "dataset_checksum": record.dataset_checksum,
        "manifest_checksum": record.manifest_checksum,
        "created_at": record.created_at.isoformat(),
        "retention_until": record.retention_until.isoformat(),
        "deletion_due_at": record.deletion_due_at.isoformat(),
        "legal_hold": record.legal_hold,
        "legal_hold_ref": record.legal_hold_ref,
        "deleted_at": record.deleted_at.isoformat() if record.deleted_at else None,
        "available": record.storage_ref is not None,
    }


__all__ = ["make_trajectory_dataset_routes"]
