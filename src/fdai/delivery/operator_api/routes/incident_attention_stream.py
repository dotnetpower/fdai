"""Authenticated durable active-incident stream for browser attention."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

from fdai.delivery.operator_api.persistence.read_model_contracts import IncidentSummary
from fdai.delivery.operator_api.read_model import ConsoleReadModel
from fdai.delivery.operator_api.streaming.sse_protocol import encode_sse_frame

_KEEPALIVE = b": keepalive\n\n"


def incident_attention_projection(incident: IncidentSummary) -> dict[str, Any] | None:
    """Return bounded binding and display fields for one active incident."""

    if incident.incident_id is None:
        return None
    return {
        "incident_id": incident.incident_id,
        "correlation_id": incident.correlation_id,
        "title": incident.title,
        "severity": incident.severity,
        "status": incident.status,
        "opened_at": incident.opened_at,
        "last_updated_at": incident.last_updated_at,
    }


async def incident_attention_snapshot(
    *,
    read_model: ConsoleReadModel,
    now: datetime,
) -> dict[str, Any]:
    page = await read_model.list_incidents(status="active", limit=50)
    incidents = [
        projection
        for incident in page.items
        if (projection := incident_attention_projection(incident)) is not None
    ]
    return {
        "event": "incident_attention.snapshot",
        "ts": now.astimezone(UTC).isoformat(),
        "incidents": incidents,
    }


def make_incident_attention_stream_route(
    *,
    read_model: ConsoleReadModel,
    authorize: Callable[[Request], Awaitable[str]],
    path: str = "/incidents/stream",
    poll_seconds: float = 2.0,
    keepalive_seconds: float = 15.0,
) -> Route:
    if not path.startswith("/"):
        raise ValueError("incident attention stream path MUST start with '/'")
    if poll_seconds <= 0 or keepalive_seconds <= 0:
        raise ValueError("incident attention stream intervals MUST be positive")

    async def handler(request: Request) -> Response:
        await authorize(request)

        async def stream() -> AsyncIterator[bytes]:
            prior = ""
            keepalive_elapsed = 0.0
            while not await request.is_disconnected():
                payload = await incident_attention_snapshot(
                    read_model=read_model,
                    now=datetime.now(UTC),
                )
                canonical = json.dumps(payload["incidents"], sort_keys=True, separators=(",", ":"))
                if canonical != prior:
                    prior = canonical
                    keepalive_elapsed = 0.0
                    yield encode_sse_frame(payload, kind="incident-attention")
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
    "incident_attention_projection",
    "incident_attention_snapshot",
    "make_incident_attention_stream_route",
]
