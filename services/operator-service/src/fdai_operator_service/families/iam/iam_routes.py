"""Authenticated IAM projection and governed human access-request routes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from fdai_service_contracts import OperatorRole
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai_operator_service.families.iam.capabilities import (
    ROLE_CAPABILITIES,
    IamCapability,
    capabilities_for,
    has_capability,
)
from fdai_operator_service.families.iam.contracts import (
    AccessRequestCommand,
    AccessRequestQuery,
    AccessReviewCommand,
    AuthorizePrincipal,
    HumanAccessRequestOutbox,
    HumanIdentityDirectory,
)
from fdai_operator_service.families.iam.errors import IamFamilyError
from fdai_operator_service.families.iam.http import (
    error_response,
    family_error,
    read_json_object,
    require_string,
)

_MAX_BODY_BYTES: Final = 16_000


def make_iam_routes(
    *,
    outbox: HumanAccessRequestOutbox | None,
    authorize: AuthorizePrincipal,
    authenticate: AuthorizePrincipal,
    directory: HumanIdentityDirectory | None = None,
    identity_provider: str = "entra",
    role_group_ids: Mapping[str, str] | None = None,
) -> tuple[Route, ...]:
    """Build IAM routes whose writes stop at durable request and review records."""

    async def get_iam(request: Request) -> Response:
        principal = await authorize(request)
        return JSONResponse(
            {
                "principal": {
                    "oid": principal.oid,
                    "roles": sorted(role.value for role in principal.roles),
                    "capabilities": sorted(
                        item.value for item in capabilities_for(principal.roles)
                    ),
                },
                "roles": [
                    {
                        "value": role.value,
                        "capabilities": sorted(item.value for item in ROLE_CAPABILITIES[role]),
                        "routine_assignment": role is not OperatorRole.BREAK_GLASS,
                    }
                    for role in OperatorRole
                ],
                "assignment_boundary": "identity-provider-group",
            }
        )

    async def get_self(request: Request) -> Response:
        principal = await authenticate(request)
        if outbox is None:
            return error_response(503, "human access request outbox is not configured")
        try:
            items, _ = await outbox.list_request_page(
                AccessRequestQuery(principal=principal, limit=20)
            )
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse(
            {
                "principal": {
                    "subject_id": principal.oid,
                    "username": principal.username,
                    "roles": sorted(role.value for role in principal.roles),
                },
                "request": dict(items[0]) if items else None,
                "can_access_console": bool(principal.roles),
            }
        )

    async def search_directory(request: Request) -> Response:
        principal = await authorize(request)
        denied = _require_manager(principal.roles)
        if denied is not None:
            return denied
        if directory is None:
            return error_response(501, "human identity directory is not configured")
        try:
            limit = int(request.query_params.get("limit", "20"))
            identities = await directory.search(request.query_params.get("q", ""), limit=limit)
        except ValueError as exc:
            return error_response(400, str(exc))
        except Exception:  # noqa: BLE001 - provider failures are redacted and fail closed.
            return error_response(503, "human identity directory is unavailable")
        return JSONResponse(
            {"provider": identity_provider, "items": [item.to_dict() for item in identities]}
        )

    async def list_directory_roster(request: Request) -> Response:
        principal = await authorize(request)
        denied = _require_manager(principal.roles)
        if denied is not None:
            return denied
        if directory is None:
            return error_response(501, "human identity directory is not configured")
        if not role_group_ids:
            return error_response(501, "IAM role groups are not configured")
        try:
            identities = await directory.list_role_roster(role_group_ids, limit=500)
        except ValueError as exc:
            return error_response(400, str(exc))
        except Exception:  # noqa: BLE001 - provider failures are redacted and fail closed.
            return error_response(503, "human identity directory is unavailable")
        return JSONResponse({"items": [item.to_dict() for item in identities]})

    async def list_access_requests(request: Request) -> Response:
        principal = await authorize(request)
        denied = _require_manager(principal.roles)
        if denied is not None:
            return denied
        if outbox is None:
            return error_response(503, "human access request outbox is not configured")
        try:
            limit = int(request.query_params.get("limit", "50"))
            offset = int(request.query_params.get("cursor", "0"))
            items, total = await outbox.list_request_page(
                AccessRequestQuery(principal=principal, limit=limit, offset=offset)
            )
        except (ValueError, IamFamilyError) as exc:
            if isinstance(exc, IamFamilyError):
                return family_error(exc)
            return error_response(400, str(exc))
        next_cursor = offset + len(items) if offset + len(items) < total else None
        return JSONResponse(
            {"items": [dict(item) for item in items], "total": total, "next_cursor": next_cursor}
        )

    async def submit_access_request(request: Request) -> Response:
        principal = await authorize(request)
        if not has_capability(principal.roles, IamCapability.AUTHOR_DRAFT_PR):
            return error_response(403, "author-draft-pr capability is required")
        return await _submit_access(
            request,
            principal=principal,
            outbox=outbox,
            directory=directory,
            identity_provider=identity_provider,
            self_service=False,
        )

    async def submit_self_access_request(request: Request) -> Response:
        principal = await authenticate(request)
        return await _submit_access(
            request,
            principal=principal,
            outbox=outbox,
            directory=None,
            identity_provider=identity_provider,
            self_service=True,
        )

    async def review_access_request(request: Request) -> Response:
        principal = await authorize(request)
        denied = _require_manager(principal.roles)
        if denied is not None:
            return denied
        if outbox is None:
            return error_response(503, "human access request outbox is not configured")
        try:
            body = await read_json_object(request, maximum=_MAX_BODY_BYTES)
            reviewed = await outbox.review(
                AccessReviewCommand(
                    principal=principal,
                    request_id=str(request.path_params["request_id"]),
                    decision=require_string(body, "decision"),
                    justification=require_string(body, "justification"),
                )
            )
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse(dict(reviewed))

    return (
        Route("/iam", get_iam, methods=["GET"]),
        Route("/iam/self", get_self, methods=["GET"]),
        Route("/iam/directory/users", search_directory, methods=["GET"]),
        Route("/iam/directory/roster", list_directory_roster, methods=["GET"]),
        Route("/iam/access-requests", list_access_requests, methods=["GET"]),
        Route("/iam/access-requests", submit_access_request, methods=["POST"]),
        Route(
            "/iam/access-requests/{request_id:str}/decision",
            review_access_request,
            methods=["POST"],
        ),
        Route("/iam/access-requests/self", submit_self_access_request, methods=["POST"]),
    )


async def _submit_access(
    request: Request,
    *,
    principal: Any,
    outbox: HumanAccessRequestOutbox | None,
    directory: HumanIdentityDirectory | None,
    identity_provider: str,
    self_service: bool,
) -> Response:
    if outbox is None:
        return error_response(503, "human access request outbox is not configured")
    try:
        body = await read_json_object(request, maximum=_MAX_BODY_BYTES)
        if self_service:
            if principal.roles:
                return error_response(
                    403, "self-service access requests are only available to unassigned principals"
                )
            target_subject_id = principal.oid
            target_username = principal.username or principal.oid
            operation = "grant"
            role = OperatorRole.READER
            justification = _optional_string(body, "message") or "Initial console access request."
        else:
            target_subject_id = _subject_id(body)
            target_username = require_string(body, "target_username")
            operation = require_string(body, "operation")
            role = OperatorRole(require_string(body, "role"))
            justification = require_string(body, "justification")
            if role is OperatorRole.BREAK_GLASS:
                return error_response(
                    400,
                    "BreakGlass is not available through routine access requests",
                )
            if directory is not None:
                try:
                    identity = await directory.get_by_subject_id(target_subject_id)
                except ValueError as exc:
                    return error_response(400, str(exc))
                except Exception:  # noqa: BLE001 - fail closed without provider details.
                    return error_response(503, "human identity directory is unavailable")
                if identity is None:
                    return error_response(400, "target identity was not found")
                if not identity.active:
                    return error_response(400, "target identity is inactive")
                if identity.username.casefold() != target_username.casefold():
                    return error_response(
                        400,
                        "target username does not match the identity provider",
                    )
        result = await outbox.submit(
            AccessRequestCommand(
                principal=principal,
                idempotency_key=require_string(body, "idempotency_key"),
                identity_provider=identity_provider,
                target_subject_id=target_subject_id,
                target_username=target_username,
                operation=operation,
                role=role,
                justification=justification,
                self_service=self_service,
            )
        )
    except (ValueError, IamFamilyError) as exc:
        if isinstance(exc, IamFamilyError):
            return family_error(exc)
        return error_response(400, str(exc))
    return JSONResponse(dict(result), status_code=201)


def _require_manager(roles: frozenset[OperatorRole]) -> Response | None:
    if not has_capability(roles, IamCapability.MANAGE_GROUP_MEMBERSHIP):
        return error_response(403, "manage-group-membership capability is required")
    return None


def _optional_string(value: dict[str, Any], key: str) -> str | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, str):
        raise ValueError(f"{key} MUST be a string")
    return item.strip() or None


def _subject_id(value: dict[str, Any]) -> str:
    item = value.get("target_subject_id", value.get("target_oid"))
    if not isinstance(item, str):
        raise ValueError("target_subject_id MUST be a string")
    return item


__all__ = ["make_iam_routes"]
