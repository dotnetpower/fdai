"""Non-privileged handover invitation and goal command routes."""

from __future__ import annotations

from typing import Any, Final

from fdai_service_contracts import OperatorRole
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai_operator_service.families.iam.contracts import (
    AuthorizePrincipal,
    HandoverGoalCommand,
    HandoverGoalOutbox,
)
from fdai_operator_service.families.iam.errors import IamFamilyError
from fdai_operator_service.families.iam.http import (
    error_response,
    family_error,
    read_json_object,
    require_revision,
)

_MAX_BODY_BYTES: Final = 8_192


def make_handover_routes(
    *, outbox: HandoverGoalOutbox | None, authorize: AuthorizePrincipal
) -> tuple[Route, ...]:
    """Build invitation and revisioned goal request routes."""

    async def invitation(request: Request) -> Response:
        principal = await authorize(request)
        if outbox is None:
            return error_response(503, "handover goal outbox is not configured")
        session_id = request.query_params.get("session_id", "").strip()
        if not session_id:
            return error_response(400, "session_id is required")
        try:
            result = await outbox.invitation_for_session(
                subject_ref=principal.oid,
                session_id=session_id,
            )
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse({"invitation": dict(result) if result is not None else None})

    async def command(request: Request) -> Response:
        principal = await authorize(request)
        if outbox is None:
            return error_response(503, "handover goal outbox is not configured")
        goal_id = str(request.path_params["goal_id"])
        operation = str(request.path_params["operation"])
        try:
            body = await read_json_object(request, maximum=_MAX_BODY_BYTES)
            revision = require_revision(body, positive=True)
            goal = await outbox.get_goal(goal_id)
            subject_ref = goal.get("subject_ref")
            if not isinstance(subject_ref, str):
                return error_response(503, "handover goal subject is unavailable")
            response = _authorize_operation(
                operation=operation,
                principal_oid=principal.oid,
                roles=principal.roles,
                subject_ref=subject_ref,
            )
            if response is not None:
                return response
            command_value = _command_from_body(
                body,
                operation=operation,
                principal=principal,
                goal_id=goal_id,
                expected_revision=revision,
            )
            updated = await outbox.submit(command_value)
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse({"goal": dict(updated)})

    return (
        Route("/handover/goals/invitation", invitation, methods=["GET"]),
        Route(
            "/handover/goals/{goal_id:str}/{operation:str}",
            command,
            methods=["POST"],
        ),
    )


def _authorize_operation(
    *,
    operation: str,
    principal_oid: str,
    roles: frozenset[OperatorRole],
    subject_ref: str,
) -> Response | None:
    if operation == "accept":
        if OperatorRole.OWNER not in roles or principal_oid.casefold() == subject_ref.casefold():
            return error_response(403, "independent Owner review is required")
        return None
    if operation not in {"snooze", "decline", "not-applicable", "evidence"}:
        return error_response(404, "unknown handover goal command")
    if principal_oid.casefold() != subject_ref.casefold():
        return error_response(403, "goal belongs to another subject")
    return None


def _command_from_body(
    body: dict[str, Any],
    *,
    operation: str,
    principal: Any,
    goal_id: str,
    expected_revision: int,
) -> HandoverGoalCommand:
    allowed = {"expected_revision"}
    values: dict[str, str | None] = {
        "reason_ref": None,
        "evidence_ref": None,
        "digest": None,
        "kind": None,
    }
    if operation == "not-applicable":
        allowed.add("reason_ref")
        values["reason_ref"] = _required_text(body, "reason_ref")
    elif operation == "evidence":
        allowed.update({"evidence_ref", "digest", "kind"})
        values.update(
            {
                "evidence_ref": _required_text(body, "evidence_ref"),
                "digest": _required_text(body, "digest"),
                "kind": _required_text(body, "kind"),
            }
        )
    if set(body) != allowed:
        raise IamFamilyError("handover goal body fields do not match")
    return HandoverGoalCommand(
        principal=principal,
        goal_id=goal_id,
        operation=operation,
        expected_revision=expected_revision,
        reason_ref=values["reason_ref"],
        evidence_ref=values["evidence_ref"],
        digest=values["digest"],
        kind=values["kind"],
    )


def _required_text(body: dict[str, Any], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str):
        raise IamFamilyError(f"{key} is required")
    return value


__all__ = ["make_handover_routes"]
