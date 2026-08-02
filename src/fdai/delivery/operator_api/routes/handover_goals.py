"""Non-privileged handover invitation and goal lifecycle routes."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from fdai.core.human_assignment import (
    GoalEvidence,
    HandoverGoalService,
    HandoverInvitation,
)
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role

Authorize = Callable[[Request], Awaitable[str]]
AuthorizePrincipal = Callable[[Request], Awaitable[Principal]]
_MAX_BODY_BYTES = 8_192


def make_handover_goal_routes(
    *,
    service: HandoverGoalService,
    authorize: Authorize,
    authorize_principal: AuthorizePrincipal,
) -> tuple[Route, ...]:
    async def invitation(request: Request) -> JSONResponse:
        subject_ref = await authorize(request)
        session_id = request.query_params.get("session_id", "").strip()
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required")
        result = await service.invitation_for_session(
            subject_ref=subject_ref,
            session_id=session_id,
        )
        return JSONResponse(
            {"invitation": _invitation_dict(result) if result is not None else None}
        )

    async def command(request: Request) -> JSONResponse:
        principal = await authorize_principal(request)
        goal_id = request.path_params["goal_id"]
        operation = request.path_params["operation"]
        body = await _body(request)
        revision = body.get("expected_revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise HTTPException(status_code=400, detail="expected_revision MUST be positive")
        goal = await service.get_goal(goal_id)
        if operation == "accept":
            if (
                Role.OWNER not in principal.roles
                or principal.oid.casefold() == goal.subject_ref.casefold()
            ):
                raise HTTPException(status_code=403, detail="independent Owner review is required")
            _keys(body, {"expected_revision"})
            updated = await service.accept(goal_id=goal_id, expected_revision=revision)
        else:
            if principal.oid.casefold() != goal.subject_ref.casefold():
                raise HTTPException(status_code=403, detail="goal belongs to another subject")
            if operation == "snooze":
                _keys(body, {"expected_revision"})
                updated = await service.snooze(goal_id=goal_id, expected_revision=revision)
            elif operation == "decline":
                _keys(body, {"expected_revision"})
                updated = await service.decline(goal_id=goal_id, expected_revision=revision)
            elif operation == "not-applicable":
                _keys(body, {"expected_revision", "reason_ref"})
                reason_ref = body.get("reason_ref")
                if not isinstance(reason_ref, str):
                    raise HTTPException(status_code=400, detail="reason_ref is required")
                updated = await service.mark_not_applicable(
                    goal_id=goal_id,
                    expected_revision=revision,
                    reason_ref=reason_ref,
                )
            elif operation == "evidence":
                _keys(body, {"expected_revision", "evidence_ref", "digest", "kind"})
                evidence_keys = ("evidence_ref", "digest", "kind")
                if not all(isinstance(body.get(key), str) for key in evidence_keys):
                    raise HTTPException(status_code=400, detail="evidence fields are required")
                updated = await service.add_evidence(
                    goal_id=goal_id,
                    expected_revision=revision,
                    evidence=GoalEvidence(
                        evidence_ref=str(body["evidence_ref"]),
                        digest=str(body["digest"]),
                        kind=str(body["kind"]),
                    ),
                )
            else:
                raise HTTPException(status_code=404, detail="unknown handover goal command")
        return JSONResponse({"goal": updated.to_dict()})

    return (
        Route("/handover/goals/invitation", invitation, methods=["GET"]),
        Route(
            "/handover/goals/{goal_id:str}/{operation:str}",
            command,
            methods=["POST"],
        ),
    )


async def _body(request: Request) -> dict[str, Any]:
    content = await request.body()
    if len(content) > _MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="handover goal body too large")
    try:
        value = json.loads(content) if content else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="handover goal body MUST be JSON") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="handover goal body MUST be an object")
    return value


def _keys(body: dict[str, Any], allowed: set[str]) -> None:
    if set(body) != allowed:
        raise HTTPException(status_code=400, detail="handover goal body fields do not match")


def _invitation_dict(value: HandoverInvitation) -> dict[str, object]:
    return {
        "invitation_id": value.invitation_id,
        "goal_id": value.goal_id,
        "agent_name": value.agent_name,
        "prompt_ref": value.prompt_ref,
        "session_id": value.session_id,
        "max_questions": value.max_questions,
        "max_minutes": value.max_minutes,
        "commands": ["evidence", "snooze", "decline", "not-applicable"],
    }


__all__ = ["make_handover_goal_routes"]
