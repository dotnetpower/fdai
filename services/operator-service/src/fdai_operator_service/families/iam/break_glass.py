"""Break-Glass activation request route.

Records a time-boxed emergency activation with an incident id and a future
expiry. The route persists an audit record only: it never elevates a runtime
principal, never grants runtime HIL approval eligibility, and never issues or
returns executor identity
(``docs/roadmap/interfaces/user-rbac-and-identity.md`` sections 2 and 10.7).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Final

from fdai_operator_service.families.iam.capabilities import IamCapability, has_capability
from fdai_operator_service.families.iam.contracts import (
    AuthorizePrincipal,
    BreakGlassActivationCommand,
    BreakGlassActivationOutbox,
)
from fdai_operator_service.families.iam.errors import IamFamilyError
from fdai_operator_service.families.iam.http import (
    error_response,
    family_error,
    read_json_object,
)
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

DEFAULT_BREAK_GLASS_ACTIVATION_PATH: Final = "/system/break-glass/activation"
DEFAULT_MAX_ACTIVATION = timedelta(hours=8)
_MAX_BODY_BYTES: Final = 16_000
_MAX_INCIDENT_ID: Final = 128
_MAX_REASON: Final = 2_000


def make_break_glass_activation_route(
    *,
    outbox: BreakGlassActivationOutbox | None,
    authorize: AuthorizePrincipal,
    clock: Callable[[], datetime] | None = None,
    maximum_activation: timedelta = DEFAULT_MAX_ACTIVATION,
    path: str = DEFAULT_BREAK_GLASS_ACTIVATION_PATH,
) -> Route:
    """Build the activation-request route with no role elevation of any kind."""
    if not path.startswith("/"):
        raise ValueError("break-glass activation path MUST start with '/'")
    if maximum_activation <= timedelta(0):
        raise ValueError("maximum_activation MUST be positive")
    now = clock or (lambda: datetime.now(UTC))

    async def handler(request: Request) -> Response:
        principal = await authorize(request)
        if not has_capability(principal.roles, IamCapability.ACTIVATE_BREAK_GLASS):
            return error_response(
                403,
                "break-glass activation requires capability 'activate-break-glass'",
            )
        if outbox is None:
            return error_response(503, "break-glass activation store is not configured")
        body = await read_json_object(request, maximum=_MAX_BODY_BYTES)
        incident_id = body.get("incident_id")
        if not isinstance(incident_id, str) or not incident_id.strip():
            return error_response(400, "incident_id MUST be a non-empty string")
        incident_id = incident_id.strip()
        if len(incident_id) > _MAX_INCIDENT_ID:
            return error_response(400, "incident_id is too long")
        reason = body.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            return error_response(400, "reason MUST be a non-empty string")
        reason = reason.strip()
        if len(reason) > _MAX_REASON:
            return error_response(400, "reason is too long")
        expires_at = _timestamp(body.get("expires_at"))
        if expires_at is None:
            return error_response(400, "expires_at MUST be an RFC 3339 timestamp with offset")
        activated_at = now()
        if expires_at <= activated_at:
            return error_response(400, "expires_at MUST be in the future")
        if expires_at - activated_at > maximum_activation:
            return error_response(
                400,
                f"expires_at exceeds the maximum activation of {maximum_activation}",
            )
        try:
            record = await outbox.activate(
                BreakGlassActivationCommand(
                    actor_oid=principal.oid,
                    incident_id=incident_id,
                    reason=reason,
                    activated_at=activated_at,
                    expires_at=expires_at,
                )
            )
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse(record.to_dict(), status_code=201)

    return Route(path, handler, methods=["POST"])


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return None if parsed.tzinfo is None else parsed


__all__ = [
    "DEFAULT_BREAK_GLASS_ACTIVATION_PATH",
    "DEFAULT_MAX_ACTIVATION",
    "make_break_glass_activation_route",
]
