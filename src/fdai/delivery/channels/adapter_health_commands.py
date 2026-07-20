"""Separately authenticated ChatOps commands for adapter health controls."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.conversation.adapter_health import AdapterHealthError, AdapterHealthService
from fdai.shared.providers.conversation_channel import ConversationChannelKind

_MAX_BODY_BYTES = 4096


class AdapterHealthCommandAuthenticator(Protocol):
    async def authenticate(self, request: Request) -> str | None: ...


def make_adapter_health_command_routes(
    *,
    service: AdapterHealthService,
    authenticator: AdapterHealthCommandAuthenticator,
    clock: Callable[[], datetime] | None = None,
    prefix: str = "/commands/adapters",
) -> tuple[Route, ...]:
    """Build command-plane routes; these routes are never mounted in the console API."""
    now = clock or (lambda: datetime.now(UTC))

    async def status(request: Request) -> Response:
        actor_id = await authenticator.authenticate(request)
        if actor_id is None:
            return _error(401, "unauthorized")
        adapter_id = request.path_params["adapter_id"]
        record = await service.status(adapter_id=adapter_id)
        if record is None:
            return _error(404, "adapter status is unavailable")
        return JSONResponse(_record_payload(record, actor_id=actor_id))

    async def pause(request: Request) -> Response:
        actor_id = await authenticator.authenticate(request)
        if actor_id is None:
            return _error(401, "unauthorized")
        payload = await _payload(request)
        if isinstance(payload, Response):
            return payload
        try:
            channel_kind = ConversationChannelKind(_required(payload, "channel_kind"))
            record = await service.pause(
                adapter_id=request.path_params["adapter_id"],
                channel_kind=channel_kind,
                actor_id=actor_id,
                reason=_required(payload, "reason"),
                at=now(),
            )
        except (AdapterHealthError, ValueError) as exc:
            return _error(403, str(exc))
        return JSONResponse(_record_payload(record, actor_id=actor_id))

    async def resume(request: Request) -> Response:
        actor_id = await authenticator.authenticate(request)
        if actor_id is None:
            return _error(401, "unauthorized")
        payload = await _payload(request)
        if isinstance(payload, Response):
            return payload
        try:
            record = await service.resume(
                adapter_id=request.path_params["adapter_id"],
                actor_id=actor_id,
                reason=_required(payload, "reason"),
                at=now(),
            )
        except AdapterHealthError as exc:
            return _error(403, str(exc))
        return JSONResponse(_record_payload(record, actor_id=actor_id))

    return (
        Route(f"{prefix}/{{adapter_id:str}}", status, methods=["GET"]),
        Route(f"{prefix}/{{adapter_id:str}}/pause", pause, methods=["POST"]),
        Route(f"{prefix}/{{adapter_id:str}}/resume", resume, methods=["POST"]),
    )


async def _payload(request: Request) -> dict[str, object] | Response:
    body = await request.body()
    if not body or len(body) > _MAX_BODY_BYTES:
        return _error(400, "request body is missing or too large")
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "request body is invalid JSON")
    if not isinstance(value, dict):
        return _error(400, "request body MUST be an object")
    return value


def _required(payload: dict[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise AdapterHealthError(f"{name} MUST be bounded non-empty text")
    return value.strip()


def _record_payload(record: object, *, actor_id: str) -> dict[str, object]:
    from fdai.shared.providers.conversation_delivery import AdapterBreakerRecord

    if not isinstance(record, AdapterBreakerRecord):
        raise TypeError("adapter health service returned an invalid record")
    return {
        "adapter_id": record.adapter_id,
        "channel_kind": record.channel_kind.value,
        "mode": record.mode.value,
        "failure_count": len(record.failure_timestamps),
        "revision": record.revision,
        "updated_at": record.updated_at.isoformat(),
        "updated_by": record.updated_by,
        "reason": record.reason,
        "requested_by": actor_id,
    }


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


__all__ = ["AdapterHealthCommandAuthenticator", "make_adapter_health_command_routes"]
