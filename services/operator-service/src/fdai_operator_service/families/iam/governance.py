"""Emergency stop and configuration-review request routes."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai_operator_service.families.iam.capabilities import IamCapability, has_capability
from fdai_operator_service.families.iam.contracts import (
    AuthorizePrincipal,
    ConfigurationReviewCommand,
    ConfigurationReviewOutbox,
    KillSwitchCommand,
    KillSwitchOutbox,
)
from fdai_operator_service.families.iam.errors import IamFamilyError
from fdai_operator_service.families.iam.http import (
    error_response,
    family_error,
    read_json_object,
)

DEFAULT_KILL_SWITCH_PATH: Final = "/system/kill-switch"
_MAX_BODY_BYTES: Final = 16_000
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def make_kill_switch_route(
    *,
    outbox: KillSwitchOutbox | None,
    authorize: AuthorizePrincipal,
    path: str = DEFAULT_KILL_SWITCH_PATH,
) -> Route:
    """Build the emergency-stop request route without any provider execution port."""
    if not path.startswith("/"):
        raise ValueError("kill-switch path MUST start with '/'")

    async def handler(request: Request) -> Response:
        principal = await authorize(request)
        if not has_capability(principal.roles, IamCapability.TRIGGER_KILL_SWITCH):
            return error_response(
                403,
                "kill-switch command requires capability 'trigger-kill-switch'",
            )
        if outbox is None:
            return error_response(503, "kill-switch outbox is not configured")
        body = await read_json_object(request, maximum=_MAX_BODY_BYTES)
        engaged = body.get("engaged")
        reason = body.get("reason")
        request_id = body.get("request_id")
        if not isinstance(engaged, bool):
            return error_response(400, "engaged MUST be a boolean")
        if not isinstance(reason, str) or not isinstance(request_id, str):
            return error_response(400, "reason and request_id MUST be strings")
        try:
            state = await outbox.submit(
                KillSwitchCommand(
                    engaged=engaged,
                    actor_oid=principal.oid,
                    reason=reason,
                    request_id=request_id,
                )
            )
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse({"state": dict(state)})

    return Route(path, handler, methods=["POST"])


def make_configuration_review_routes(
    *,
    outbox: ConfigurationReviewOutbox | None,
    authorize: AuthorizePrincipal,
    clock: Callable[[], datetime] | None = None,
) -> tuple[Route, ...]:
    """Build evidence-campaign request routes without executing configuration changes."""
    now = clock or (lambda: datetime.now(UTC))

    async def run_review(request: Request) -> Response:
        principal = await authorize(request)
        if not _at_least_contributor(principal.roles):
            return error_response(403, "configuration review requires Contributor")
        if outbox is None:
            return error_response(503, "configuration review outbox is not configured")
        run_id = request.headers.get("idempotency-key", "").strip()
        if _RUN_ID.fullmatch(run_id) is None:
            return error_response(400, "valid Idempotency-Key header is required")
        try:
            result = await outbox.run(
                ConfigurationReviewCommand(
                    principal_id=principal.oid,
                    run_id=run_id,
                    requested_at=now(),
                )
            )
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse(dict(result))

    async def resume_review(request: Request) -> Response:
        principal = await authorize(request)
        if not _at_least_approver(principal.roles):
            return error_response(403, "configuration review resume requires Approver")
        if outbox is None:
            return error_response(503, "configuration review outbox is not configured")
        try:
            result = await outbox.resume(principal_id=principal.oid)
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse(dict(result))

    return (
        Route("/configuration-baselines/review/run", run_review, methods=["POST"]),
        Route("/configuration-baselines/review/resume", resume_review, methods=["POST"]),
    )


def _at_least_contributor(roles: frozenset[object]) -> bool:
    return any(
        getattr(role, "value", None) in {"Contributor", "Approver", "Owner"} for role in roles
    )


def _at_least_approver(roles: frozenset[object]) -> bool:
    return any(getattr(role, "value", None) in {"Approver", "Owner"} for role in roles)


__all__ = [
    "DEFAULT_KILL_SWITCH_PATH",
    "make_configuration_review_routes",
    "make_kill_switch_route",
]
