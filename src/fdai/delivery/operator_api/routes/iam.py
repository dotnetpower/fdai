"""Authenticated IAM projection and governed access-request routes.

The routes expose the signed-in human's effective FDAI App Roles and allow a
Contributor-or-higher principal to submit an access-change request. They never
call Microsoft Graph and never mutate Entra group membership.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, Final

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route

from fdai.core.rbac.access_request import (
    AccessOperation,
    AccessRequestConflictError,
    AccessRequestError,
    AccessRequestPermissionError,
    AccessRequestService,
    AccessReviewDecision,
)
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import ROLE_CAPABILITIES, Capability, Role, has_capability
from fdai.shared.providers.human_identity import HumanIdentityDirectory

AuthorizePrincipal = Callable[[Request], Awaitable[Principal]]
_MAX_BODY_BYTES: Final[int] = 16_000


def append_iam_routes(
    routes: list[BaseRoute],
    *,
    service: AccessRequestService,
    authorize: AuthorizePrincipal,
    authenticate: AuthorizePrincipal,
    directory: HumanIdentityDirectory | None = None,
    identity_provider: str = "entra",
    role_group_ids: dict[str, str] | None = None,
) -> None:
    """Append IAM routes to the API route list."""

    async def get_iam(request: Request) -> Response:
        principal = await authorize(request)
        return JSONResponse(
            {
                "principal": {
                    "oid": principal.oid,
                    "roles": sorted(role.value for role in principal.roles),
                    "capabilities": sorted(
                        capability.value
                        for capability in Capability
                        if has_capability(principal.roles, capability)
                    ),
                },
                "roles": [
                    {
                        "value": role.value,
                        "capabilities": sorted(
                            capability.value for capability in ROLE_CAPABILITIES[role]
                        ),
                        "routine_assignment": role is not Role.BREAK_GLASS,
                    }
                    for role in Role
                ],
                "assignment_boundary": "identity-provider-group",
            }
        )

    async def list_access_requests(request: Request) -> Response:
        principal = await authorize(request)
        if not has_capability(principal.roles, Capability.MANAGE_GROUP_MEMBERSHIP):
            return _error(403, "manage-group-membership capability is required")
        try:
            raw_limit = request.query_params.get("limit", "50")
            limit = int(raw_limit)
            offset = int(request.query_params.get("cursor", "0"))
            items, total = await service.list_request_page(
                principal=principal,
                limit=limit,
                offset=offset,
            )
        except (ValueError, AccessRequestError) as exc:
            return _error(400, str(exc))
        next_cursor = offset + len(items) if offset + len(items) < total else None
        return JSONResponse(
            {
                "items": [item.to_dict() for item in items],
                "total": total,
                "next_cursor": next_cursor,
            }
        )

    async def get_self(request: Request) -> Response:
        principal = await authenticate(request)
        items = await service.list_requests(principal=principal, limit=20)
        return JSONResponse(
            {
                "principal": {
                    "subject_id": principal.oid,
                    "username": principal.upn or principal.email,
                    "roles": sorted(role.value for role in principal.roles),
                },
                "request": items[0].to_dict() if items else None,
                "can_access_console": bool(principal.roles),
            }
        )

    async def submit_self_access_request(request: Request) -> Response:
        principal = await authenticate(request)
        try:
            body = await _read_json_object(request)
            message = _optional_string(body, "message") or "Initial console access request."
            access_request = await service.submit(
                principal=principal,
                idempotency_key=_string(body, "idempotency_key"),
                identity_provider=identity_provider,
                target_subject_id=principal.oid,
                target_username=principal.upn or principal.email or principal.oid,
                operation=AccessOperation.GRANT,
                role=Role.READER,
                justification=message,
                self_service=True,
            )
        except AccessRequestPermissionError as exc:
            return _error(403, str(exc))
        except AccessRequestConflictError as exc:
            return _error(409, str(exc))
        except (AccessRequestError, ValueError) as exc:
            return _error(400, str(exc))
        return JSONResponse(access_request.to_dict(), status_code=201)

    async def search_directory(request: Request) -> Response:
        principal = await authorize(request)
        if not has_capability(principal.roles, Capability.MANAGE_GROUP_MEMBERSHIP):
            return _error(403, "manage-group-membership capability is required")
        if directory is None:
            return _error(501, "human identity directory is not configured")
        try:
            query = request.query_params.get("q", "")
            raw_limit = request.query_params.get("limit", "20")
            identities = await directory.search(query, limit=int(raw_limit))
        except ValueError as exc:
            return _error(400, str(exc))
        except Exception:  # noqa: BLE001 - provider failures fail closed at the boundary
            return _error(503, "human identity directory is unavailable")
        return JSONResponse(
            {
                "provider": identity_provider,
                "items": [identity.to_dict() for identity in identities],
            }
        )

    async def list_directory_roster(request: Request) -> Response:
        principal = await authorize(request)
        if not has_capability(principal.roles, Capability.MANAGE_GROUP_MEMBERSHIP):
            return _error(403, "manage-group-membership capability is required")
        if directory is None:
            return _error(501, "human identity directory is not configured")
        if not role_group_ids:
            return _error(501, "IAM role groups are not configured")
        try:
            items = await directory.list_role_roster(role_group_ids, limit=500)
        except ValueError as exc:
            return _error(400, str(exc))
        except Exception:  # noqa: BLE001 - provider failures fail closed at the boundary
            return _error(503, "human identity directory is unavailable")
        return JSONResponse({"items": [item.to_dict() for item in items]})

    async def submit_access_request(request: Request) -> Response:
        principal = await authorize(request)
        try:
            body = await _read_json_object(request)
            target_subject_id = _subject_id(body)
            target_username = _string(body, "target_username")
            if directory is not None:
                try:
                    identity = await directory.get_by_subject_id(target_subject_id)
                except ValueError as exc:
                    return _error(400, str(exc))
                except Exception:  # noqa: BLE001 - provider failures fail closed
                    return _error(503, "human identity directory is unavailable")
                if identity is None:
                    return _error(400, "target identity was not found")
                if not identity.active:
                    return _error(400, "target identity is inactive")
                if identity.username.casefold() != target_username.casefold():
                    return _error(400, "target username does not match the identity provider")
            access_request = await service.submit(
                principal=principal,
                idempotency_key=_string(body, "idempotency_key"),
                identity_provider=identity_provider,
                target_subject_id=target_subject_id,
                target_username=target_username,
                operation=AccessOperation(_string(body, "operation")),
                role=Role(_string(body, "role")),
                justification=_string(body, "justification"),
            )
        except AccessRequestPermissionError as exc:
            return _error(403, str(exc))
        except AccessRequestConflictError as exc:
            return _error(409, str(exc))
        except (AccessRequestError, ValueError) as exc:
            return _error(400, str(exc))
        return JSONResponse(access_request.to_dict(), status_code=201)

    async def review_access_request(request: Request) -> Response:
        principal = await authorize(request)
        try:
            body = await _read_json_object(request)
            reviewed = await service.review(
                principal=principal,
                request_id=request.path_params["request_id"],
                decision=AccessReviewDecision(_string(body, "decision")),
                justification=_string(body, "justification"),
            )
        except AccessRequestPermissionError as exc:
            return _error(403, str(exc))
        except AccessRequestConflictError as exc:
            return _error(409, str(exc))
        except (AccessRequestError, ValueError) as exc:
            return _error(400, str(exc))
        return JSONResponse(reviewed.to_dict())

    routes.extend(
        (
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
            Route(
                "/iam/access-requests/self",
                submit_self_access_request,
                methods=["POST"],
            ),
        )
    )


async def _read_json_object(request: Request) -> dict[str, Any]:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > _MAX_BODY_BYTES:
                raise AccessRequestError(f"request body MUST be at most {_MAX_BODY_BYTES} bytes")
        except ValueError as exc:
            raise AccessRequestError("content-length MUST be an integer") from exc
    body = await request.body()
    if len(body) > _MAX_BODY_BYTES:
        raise AccessRequestError(f"request body MUST be at most {_MAX_BODY_BYTES} bytes")
    try:
        value = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AccessRequestError("request body MUST be a JSON object") from exc
    if not isinstance(value, dict):
        raise AccessRequestError("request body MUST be a JSON object")
    return value


def _string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise AccessRequestError(f"{key} MUST be a string")
    return item


def _optional_string(value: dict[str, Any], key: str) -> str | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, str):
        raise AccessRequestError(f"{key} MUST be a string")
    return item.strip() or None


def _subject_id(value: dict[str, Any]) -> str:
    item = value.get("target_subject_id", value.get("target_oid"))
    if not isinstance(item, str):
        raise AccessRequestError("target_subject_id MUST be a string")
    return item


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"status": status, "message": message}},
        status_code=status,
    )


__all__ = ["append_iam_routes"]
