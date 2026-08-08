"""Execution access-grant decision and replayable SSE transport routes."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Final

from fdai_operator_service.families.iam.contracts import (
    AccessGrantDecisionCommand,
    AccessGrantOutbox,
    AccessGrantSnapshot,
    AccessGrantSnapshotQuery,
    AuthorizePrincipal,
)
from fdai_operator_service.families.iam.errors import IamFamilyError
from fdai_operator_service.families.iam.http import (
    error_response,
    family_error,
    read_json_object,
    require_revision,
    require_string,
)
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

_MAX_BODY_BYTES: Final = 8_192
_MAX_REASON_CHARS: Final = 2_000
_FIELDS = frozenset({"decision", "reason", "expected_revision"})
_KEEPALIVE = b": keepalive\n\n"


def make_access_grant_routes(
    *,
    outbox: AccessGrantOutbox | None,
    authorize: AuthorizePrincipal,
    poll_seconds: float = 2.0,
    keepalive_seconds: float = 15.0,
    clock: Callable[[], datetime] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> tuple[Route, ...]:
    """Build grant review and principal-scoped replay routes without applying access."""
    if poll_seconds <= 0 or keepalive_seconds <= 0:
        raise ValueError("access grant stream intervals MUST be positive")
    now = clock or (lambda: datetime.now(UTC))

    async def handler(request: Request) -> Response:
        if outbox is None:
            return error_response(503, "execution access grant outbox is not configured")
        principal = await authorize(request)
        try:
            body = await _decision_body(request)
            result = await outbox.decide(
                AccessGrantDecisionCommand(
                    request_id=str(request.path_params["request_id"]),
                    reviewer_ref=principal.oid,
                    reviewer_roles=frozenset(role.value for role in principal.roles),
                    decision=require_string(body, "decision"),
                    reason=require_string(body, "reason").strip(),
                    expected_revision=require_revision(body),
                    decided_at=now(),
                )
            )
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse(
            {
                "request_id": result.request_id,
                "status": result.status,
                "revision": result.revision,
                "approved_count": result.approved_count,
                "quorum": result.quorum,
                "reviewed_at": result.reviewed_at.astimezone(UTC).isoformat()
                if result.reviewed_at is not None
                else None,
                "permission_applied": False,
                "fresh_probe_required": True,
            }
        )

    decision_route = Route(
        "/access-grants/{request_id:str}/decision",
        handler,
        methods=["POST"],
    )

    async def handler(request: Request) -> Response:  # type: ignore[no-redef]
        if outbox is None:
            return error_response(503, "execution access grant outbox is not configured")
        principal = await authorize(request)
        try:
            after_sequence = _last_event_id(request)
            snapshot = await outbox.snapshot(
                AccessGrantSnapshotQuery(
                    reviewer_ref=principal.oid,
                    reviewer_roles=frozenset(role.value for role in principal.roles),
                    after_sequence=after_sequence,
                )
            )
        except IamFamilyError as exc:
            return family_error(exc)

        async def stream() -> AsyncIterator[bytes]:
            current = snapshot
            canonical = ""
            keepalive_elapsed = 0.0
            while not await request.is_disconnected():
                current_canonical = json.dumps(
                    [item.to_dict() for item in current.requests],
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if current_canonical != canonical:
                    canonical = current_canonical
                    keepalive_elapsed = 0.0
                    yield access_grant_sse_frame(current)
                elif keepalive_elapsed >= keepalive_seconds:
                    keepalive_elapsed = 0.0
                    yield _KEEPALIVE
                await sleep(poll_seconds)
                keepalive_elapsed += poll_seconds
                current = await outbox.snapshot(
                    AccessGrantSnapshotQuery(
                        reviewer_ref=principal.oid,
                        reviewer_roles=frozenset(role.value for role in principal.roles),
                        after_sequence=current.sequence,
                    )
                )

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    stream_route = Route("/access-grants/stream", handler, methods=["GET"])
    return decision_route, stream_route


def access_grant_sse_frame(snapshot: AccessGrantSnapshot) -> bytes:
    """Encode one bounded snapshot with a durable replay sequence."""
    payload = {
        "event": "access_grant.snapshot",
        "ts": snapshot.generated_at.astimezone(UTC).isoformat(),
        "requests": [item.to_dict() for item in snapshot.requests],
    }
    data = json.dumps(payload, separators=(",", ":"))
    return (f"id: {snapshot.sequence}\nevent: access-grant\ndata: {data}\n\n").encode()


async def _decision_body(request: Request) -> dict[str, Any]:
    body = await read_json_object(request, maximum=_MAX_BODY_BYTES)
    if set(body) != _FIELDS:
        raise IamFamilyError(
            "access grant decision body MUST contain only decision, reason, and expected_revision"
        )
    if body.get("decision") not in {"approve", "reject"}:
        raise IamFamilyError("access grant decision MUST be approve or reject")
    reason = body.get("reason")
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > _MAX_REASON_CHARS:
        raise IamFamilyError("access grant decision reason MUST be between 1 and 2000 chars")
    require_revision(body)
    body["reason"] = reason.strip()
    return body


def _last_event_id(request: Request) -> int | None:
    raw = request.headers.get("last-event-id")
    if raw is None or raw == "":
        return None
    try:
        sequence = int(raw)
    except ValueError as exc:
        raise IamFamilyError("Last-Event-ID MUST be a non-negative integer") from exc
    if sequence < 0:
        raise IamFamilyError("Last-Event-ID MUST be a non-negative integer")
    return sequence


__all__ = ["access_grant_sse_frame", "make_access_grant_routes"]
