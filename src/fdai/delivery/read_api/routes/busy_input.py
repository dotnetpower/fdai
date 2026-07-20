"""Authenticated HTTP surface for follow-ups to a busy conversation session."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from fdai.core.conversation import (
    BusyInput,
    BusyInputConflictError,
    BusyInputCoordinator,
    BusyInputKind,
    BusyInputMode,
    BusySessionState,
)
from fdai.delivery.read_api.routes.chat_route_common import AuthorizeFn

DEFAULT_BUSY_INPUT_PATH: Final = "/chat/busy-input"
MAX_BUSY_INPUT_BODY_BYTES: Final = 8_192
MAX_BUSY_INPUT_EXPIRY_SECONDS: Final = 3_600
DEFAULT_BUSY_INPUT_EXPIRY_SECONDS: Final = 300


def make_busy_input_routes(
    *,
    coordinator: BusyInputCoordinator,
    authorize: AuthorizeFn,
    path: str = DEFAULT_BUSY_INPUT_PATH,
    now: Callable[[], datetime] | None = None,
) -> tuple[Route, ...]:
    """Build the owner-scoped busy-input submit, inspect, mode, and cancel routes."""

    clock = now or (lambda: datetime.now(UTC))

    async def submit(request: Request) -> JSONResponse:
        principal_id = await authorize(request)
        body = await _body(request)
        session_id = _identifier(body, "session_id")
        await _owned_state(coordinator, session_id, principal_id)
        received_at = clock()
        expires_in = _expiry_seconds(body)
        try:
            incoming = BusyInput(
                input_id=_identifier(body, "input_id"),
                idempotency_key=_identifier(body, "idempotency_key"),
                session_id=session_id,
                principal_id=principal_id,
                content=_content(body),
                kind=_kind(body),
                received_at=received_at,
                expires_at=received_at + timedelta(seconds=expires_in),
            )
            decision = await coordinator.submit(incoming, now=received_at)
        except (BusyInputConflictError, ValueError) as exc:
            if isinstance(exc, BusyInputConflictError):
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(
            {
                "disposition": decision.record.disposition.value,
                "session_id": session_id,
                "input_id": decision.record.input.input_id,
                "sequence": decision.record.sequence,
                "reason": decision.reason,
                "duplicate": decision.duplicate,
            },
            status_code=202,
        )

    async def inspect(request: Request) -> JSONResponse:
        principal_id = await authorize(request)
        session_id = _query_session_id(request)
        state = await _owned_state(coordinator, session_id, principal_id)
        pending = await coordinator.pending(session_id=session_id, principal_id=principal_id)
        return JSONResponse(
            {
                "session_id": session_id,
                "mode": state.mode.value,
                "active": state.active_turn_id is not None,
                "revision": state.revision,
                "pending": [
                    {
                        "input_id": item.input.input_id,
                        "sequence": item.sequence,
                        "disposition": item.disposition.value,
                        "kind": item.input.kind.value,
                        "content": item.input.content,
                        "expires_at": item.input.expires_at.isoformat(),
                    }
                    for item in pending
                ],
            }
        )

    async def set_mode(request: Request) -> JSONResponse:
        principal_id = await authorize(request)
        body = await _body(request)
        session_id = _identifier(body, "session_id")
        try:
            mode = BusyInputMode(str(body.get("mode", "")))
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="mode MUST be queue, interrupt, or steer"
            ) from exc
        try:
            state = await coordinator.set_mode(
                session_id=session_id,
                principal_id=principal_id,
                mode=mode,
            )
        except BusyInputConflictError as exc:
            raise HTTPException(status_code=404, detail="busy session not found") from exc
        return JSONResponse({"session_id": session_id, "mode": state.mode.value})

    async def cancel_current(request: Request) -> JSONResponse:
        principal_id = await authorize(request)
        body = await _body(request)
        session_id = _identifier(body, "session_id")
        await _owned_state(coordinator, session_id, principal_id)
        cancelled = await coordinator.cancel_current(
            session_id=session_id,
            principal_id=principal_id,
        )
        return JSONResponse(
            {"session_id": session_id, "cancelled": cancelled},
            status_code=202 if cancelled else 409,
        )

    return (
        Route(path, submit, methods=["POST"]),
        Route(path, inspect, methods=["GET"]),
        Route(f"{path}/mode", set_mode, methods=["PUT"]),
        Route(f"{path}/cancel-current", cancel_current, methods=["POST"]),
    )


async def _body(request: Request) -> Mapping[str, Any]:
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            if int(declared_length) > MAX_BUSY_INPUT_BODY_BYTES:
                raise HTTPException(status_code=413, detail="busy input body too large")
        except ValueError:
            pass
    raw = await request.body()
    if len(raw) > MAX_BUSY_INPUT_BODY_BYTES:
        raise HTTPException(status_code=413, detail="busy input body too large")
    try:
        body = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="busy input body MUST be JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="busy input body MUST be a JSON object")
    return body


async def _owned_state(
    coordinator: BusyInputCoordinator,
    session_id: str,
    principal_id: str,
) -> BusySessionState:
    state = await coordinator.status(session_id=session_id, principal_id=principal_id)
    if state is None:
        raise HTTPException(status_code=404, detail="busy session not found")
    return state


def _query_session_id(request: Request) -> str:
    raw = request.query_params.get("session_id")
    return _bounded_identifier("session_id", raw)


def _identifier(body: Mapping[str, Any], name: str) -> str:
    raw = body.get(name)
    return _bounded_identifier(name, raw)


def _bounded_identifier(name: str, raw: object) -> str:
    if not isinstance(raw, str) or not raw.strip() or len(raw.strip()) > 256:
        raise HTTPException(status_code=400, detail=f"{name} MUST be a bounded string")
    return raw.strip()


def _content(body: Mapping[str, Any]) -> str:
    raw = body.get("content")
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=400, detail="content MUST be a non-empty string")
    return raw.strip()


def _kind(body: Mapping[str, Any]) -> BusyInputKind:
    try:
        return BusyInputKind(str(body.get("kind", BusyInputKind.PROSE.value)))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="kind is invalid") from exc


def _expiry_seconds(body: Mapping[str, Any]) -> int:
    raw = body.get("expires_in_seconds", DEFAULT_BUSY_INPUT_EXPIRY_SECONDS)
    if (
        isinstance(raw, bool)
        or not isinstance(raw, int)
        or not 1 <= raw <= MAX_BUSY_INPUT_EXPIRY_SECONDS
    ):
        raise HTTPException(
            status_code=400,
            detail=f"expires_in_seconds MUST be in [1, {MAX_BUSY_INPUT_EXPIRY_SECONDS}]",
        )
    return int(raw)


__all__ = [
    "DEFAULT_BUSY_INPUT_PATH",
    "DEFAULT_BUSY_INPUT_EXPIRY_SECONDS",
    "MAX_BUSY_INPUT_EXPIRY_SECONDS",
    "make_busy_input_routes",
]
