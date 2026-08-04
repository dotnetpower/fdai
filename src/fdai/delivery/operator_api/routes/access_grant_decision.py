"""Authenticated browser review for pending execution access grants."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Final

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.execution_authorization import (
    AccessGrantDecision,
    AccessGrantRequestConflictError,
    AccessGrantRequestError,
    AccessGrantRequestPermissionError,
    AccessGrantRequestService,
)
from fdai.core.rbac.resolver import Principal

_MAX_BODY_BYTES: Final[int] = 8_192
_MAX_REASON_CHARS: Final[int] = 2_000
_FIELDS = frozenset({"decision", "reason", "expected_revision"})


def make_access_grant_decision_route(
    *,
    service: AccessGrantRequestService,
    authorize: Callable[[Request], Awaitable[Principal]],
    path: str = "/access-grants/{request_id:str}/decision",
) -> Route:
    """Build the non-privileged review route for one exact request revision."""

    if not path.startswith("/"):
        raise ValueError("access grant decision path MUST start with '/'")

    async def handler(request: Request) -> Response:
        principal = await authorize(request)
        try:
            body = await _decision_body(request)
            updated = await service.decide(
                request_id=str(request.path_params["request_id"]),
                reviewer_ref=principal.oid,
                reviewer_roles=frozenset(role.value for role in principal.roles),
                decision=AccessGrantDecision(str(body["decision"])),
                reason=str(body["reason"]),
                decided_at=datetime.now(UTC),
                expected_revision=int(body["expected_revision"]),
            )
        except AccessGrantRequestPermissionError as exc:
            return _error(403, str(exc))
        except AccessGrantRequestConflictError as exc:
            return _error(409, str(exc))
        except AccessGrantRequestError as exc:
            status = 404 if "not found" in str(exc) else 400
            return _error(status, str(exc))
        return JSONResponse(
            {
                "request_id": updated.request_id,
                "status": updated.status.value,
                "revision": updated.revision,
                "approved_count": len(updated.approved_by),
                "quorum": updated.quorum,
                "reviewed_at": updated.reviewed_at.astimezone(UTC).isoformat()
                if updated.reviewed_at is not None
                else None,
                "permission_applied": False,
                "fresh_probe_required": True,
            }
        )

    return Route(path, handler, methods=["POST"])


async def _decision_body(request: Request) -> Mapping[str, Any]:
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise AccessGrantRequestError("access grant decision body is too large")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, ValueError) as exc:
        raise AccessGrantRequestError("access grant decision body MUST be JSON") from exc
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise AccessGrantRequestError(
            "access grant decision body MUST contain only decision, reason, and expected_revision"
        )
    if value.get("decision") not in {item.value for item in AccessGrantDecision}:
        raise AccessGrantRequestError("access grant decision MUST be approve or reject")
    reason = value.get("reason")
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > _MAX_REASON_CHARS:
        raise AccessGrantRequestError(
            "access grant decision reason MUST be between 1 and 2000 chars"
        )
    revision = value.get("expected_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise AccessGrantRequestError("access grant expected revision MUST be non-negative")
    return {**value, "reason": reason.strip()}


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"status": status, "message": message}},
        status_code=status,
    )


__all__ = ["make_access_grant_decision_route"]
