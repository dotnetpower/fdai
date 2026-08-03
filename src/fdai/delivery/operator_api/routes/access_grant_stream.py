"""Principal-scoped browser projection for pending execution access grants."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

from fdai.core.execution_authorization import AccessGrantRequest, AccessGrantRequestService
from fdai.core.rbac.resolver import Principal
from fdai.delivery.operator_api.streaming.sse_protocol import encode_sse_frame

_KEEPALIVE = b": keepalive\n\n"


def access_grant_projection(request: AccessGrantRequest) -> dict[str, Any]:
    """Return the bounded browser-safe fields for one durable request."""

    return {
        "request_id": request.request_id,
        "correlation_id": request.original_action_id,
        "capability_id": request.capability_id,
        "scope_ref": request.scope_ref,
        "grant_mode": request.grant_mode,
        "requested_at": request.requested_at.astimezone(UTC).isoformat(),
        "expires_at": request.expires_at.astimezone(UTC).isoformat(),
        "quorum": request.quorum,
        "status": request.status.value,
        "revision": request.revision,
    }


async def access_grant_snapshot(
    *,
    service: AccessGrantRequestService,
    principal: Principal,
    now: datetime,
) -> dict[str, Any]:
    requests = await service.list_pending_for_roles(
        reviewer_ref=principal.oid,
        reviewer_roles=frozenset(role.value for role in principal.roles),
        now=now,
        limit=50,
    )
    return {
        "event": "access_grant.snapshot",
        "ts": now.astimezone(UTC).isoformat(),
        "requests": [access_grant_projection(request) for request in requests],
    }


def make_access_grant_stream_route(
    *,
    service: AccessGrantRequestService,
    authorize: Callable[[Request], Awaitable[Principal]],
    path: str = "/access-grants/stream",
    poll_seconds: float = 2.0,
    keepalive_seconds: float = 15.0,
) -> Route:
    if not path.startswith("/"):
        raise ValueError("access grant stream path MUST start with '/'")
    if poll_seconds <= 0 or keepalive_seconds <= 0:
        raise ValueError("access grant stream intervals MUST be positive")

    async def handler(request: Request) -> Response:
        principal = await authorize(request)

        async def stream() -> AsyncIterator[bytes]:
            prior = ""
            keepalive_elapsed = 0.0
            while not await request.is_disconnected():
                payload = await access_grant_snapshot(
                    service=service,
                    principal=principal,
                    now=datetime.now(UTC),
                )
                canonical = json.dumps(payload["requests"], sort_keys=True, separators=(",", ":"))
                if canonical != prior:
                    prior = canonical
                    keepalive_elapsed = 0.0
                    yield encode_sse_frame(payload, kind="access-grant")
                elif keepalive_elapsed >= keepalive_seconds:
                    keepalive_elapsed = 0.0
                    yield _KEEPALIVE
                await asyncio.sleep(poll_seconds)
                keepalive_elapsed += poll_seconds

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return Route(path, handler, methods=["GET"])


__all__ = [
    "access_grant_projection",
    "access_grant_snapshot",
    "make_access_grant_stream_route",
]
