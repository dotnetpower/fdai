"""Owner/BreakGlass command route for the global emergency stop."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Final

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from fdai.core.rbac.kill_switch_command import (
    KillSwitchCommandConflictError,
    KillSwitchCommandError,
    KillSwitchCommandService,
)
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Capability, has_capability

DEFAULT_KILL_SWITCH_PATH: Final[str] = "/system/kill-switch"
_MAX_BODY_BYTES: Final[int] = 16_000

AuthorizePrincipal = Callable[[Request], Awaitable[Principal]]


def make_kill_switch_route(
    *,
    service: KillSwitchCommandService,
    authorize_principal: AuthorizePrincipal,
    path: str = DEFAULT_KILL_SWITCH_PATH,
) -> Route:
    """Return the authenticated emergency-stop command route."""

    async def handler(request: Request) -> JSONResponse:
        principal = await authorize_principal(request)
        if not has_capability(principal.roles, Capability.TRIGGER_KILL_SWITCH):
            raise HTTPException(
                status_code=403,
                detail=(
                    "kill-switch command requires capability "
                    f"{Capability.TRIGGER_KILL_SWITCH.value!r}"
                ),
            )
        body = await request.body()
        if len(body) > _MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="kill-switch request body is too large")
        try:
            raw = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail="request body MUST be valid JSON") from exc
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="request body MUST be a JSON object")
        engaged = raw.get("engaged")
        if not isinstance(engaged, bool):
            raise HTTPException(status_code=400, detail="engaged MUST be a boolean")
        reason = raw.get("reason")
        request_id = raw.get("request_id")
        if not isinstance(reason, str) or not isinstance(request_id, str):
            raise HTTPException(
                status_code=400,
                detail="reason and request_id MUST be strings",
            )
        try:
            state = await service.set_state(
                engaged=engaged,
                actor_oid=principal.oid,
                reason=reason,
                request_id=request_id,
            )
        except KillSwitchCommandError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KillSwitchCommandConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse({"state": state.to_dict()})

    return Route(path, handler, methods=["POST"])


__all__ = ["DEFAULT_KILL_SWITCH_PATH", "make_kill_switch_route"]
