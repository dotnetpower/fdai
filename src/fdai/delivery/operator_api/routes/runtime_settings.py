"""Authorized runtime settings projection and mutation route."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Capability, has_capability
from fdai.delivery.runtime_settings import (
    RuntimeSettingsConflictError,
    RuntimeSettingsService,
    RuntimeSettingsUnavailableError,
)

_MAX_BODY_BYTES = 16_000


def make_runtime_settings_routes(
    *,
    service: RuntimeSettingsService,
    authorize_principal: Callable[[Request], Awaitable[Principal]],
) -> tuple[Route, ...]:
    async def get_settings(request: Request) -> Response:
        principal = await authorize_principal(request)
        try:
            return JSONResponse(
                await service.projection(
                    can_manage=has_capability(
                        principal.roles,
                        Capability.MANAGE_RUNTIME_SETTINGS,
                    )
                )
            )
        except RuntimeSettingsUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    async def put_settings(request: Request) -> Response:
        principal = await authorize_principal(request)
        if not has_capability(principal.roles, Capability.MANAGE_RUNTIME_SETTINGS):
            raise HTTPException(status_code=403, detail="Owner role is required")
        body = await _read_json_body(request)
        changes = body.get("changes")
        expected_revision = body.get("expected_revision")
        if not isinstance(changes, dict):
            raise HTTPException(status_code=400, detail="changes MUST be an object")
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 0
        ):
            raise HTTPException(status_code=400, detail="expected_revision MUST be >= 0")
        try:
            await service.update(
                actor_id=principal.oid,
                changes=changes,
                expected_revision=expected_revision,
            )
            return JSONResponse(await service.projection(can_manage=True))
        except RuntimeSettingsConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeSettingsUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return (
        Route("/runtime/settings", get_settings, methods=["GET"]),
        Route("/runtime/settings", put_settings, methods=["PUT"]),
    )


async def _read_json_body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="request body too large")
    try:
        value = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="request body MUST be JSON") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="request body MUST be an object")
    return value


__all__ = ["make_runtime_settings_routes"]
