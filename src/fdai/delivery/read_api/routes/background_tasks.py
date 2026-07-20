"""Authenticated background task commands and read projections."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from fdai.core.background_task import (
    TERMINAL_BACKGROUND_STATUSES,
    BackgroundTaskAttempt,
    BackgroundTaskBudget,
    BackgroundTaskCoordinator,
    BackgroundTaskOrigin,
    BackgroundTaskService,
    BackgroundTaskStore,
)
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Capability, Role, has_capability

AuthorizePrincipal = Callable[[Request], Awaitable[Principal]]
_MAX_BODY: Final = 16_000


@dataclass(frozen=True, slots=True)
class BackgroundTaskRoutesConfig:
    service: BackgroundTaskService
    store: BackgroundTaskStore
    coordinator: BackgroundTaskCoordinator


def make_background_task_routes(
    *,
    config: BackgroundTaskRoutesConfig,
    authorize_principal: AuthorizePrincipal,
) -> tuple[Route, ...]:
    async def create_task(request: Request) -> Response:
        principal = await authorize_principal(request)
        if not has_capability(principal.roles, Capability.AUTHOR_DRAFT_PR):
            raise HTTPException(status_code=403, detail="author-draft-pr capability is required")
        body = await _body(request)
        prompt = _string(body, "prompt", maximum=4_000)
        conversation_id = _string(body, "conversation_id")
        channel_kind = _string(body, "channel_kind")
        channel_id = _string(body, "channel_id")
        idempotency_key = _string(body, "idempotency_key")
        correlation_id = _string(body, "correlation_id")
        context_digest = hashlib.sha256(
            json.dumps(
                {
                    "conversation_id": conversation_id,
                    "prompt": prompt,
                    "principal_id": principal.oid,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        attempt, created = await config.service.create(
            owner_principal_id=principal.oid,
            origin=BackgroundTaskOrigin(
                conversation_id=conversation_id,
                channel_kind=channel_kind,
                channel_id=channel_id,
                thread_id=_optional_string(body, "thread_id"),
            ),
            prompt=prompt,
            context_digest=f"sha256:{context_digest}",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            budget=_budget(body),
            retention_days=_integer(body, "retention_days", default=30),
        )
        config.coordinator.wake()
        return JSONResponse(_attempt(attempt), status_code=202 if created else 200)

    async def list_tasks(request: Request) -> Response:
        principal = await authorize_principal(request)
        tasks = await config.store.list(owner=principal.oid, limit=_query_limit(request))
        return JSONResponse({"tasks": [_attempt(item, include_prompt=False) for item in tasks]})

    async def get_task(request: Request) -> Response:
        principal = await authorize_principal(request)
        attempt = await config.store.get(request.path_params["task_id"], owner=principal.oid)
        if attempt is None:
            raise HTTPException(status_code=404, detail="background task not found")
        return JSONResponse(_attempt(attempt))

    async def get_progress(request: Request) -> Response:
        principal = await authorize_principal(request)
        try:
            events = await config.store.progress(
                request.path_params["task_id"],
                owner=principal.oid,
                limit=_query_limit(request),
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="background task not found") from exc
        return JSONResponse(
            {
                "progress": [
                    {
                        "sequence": event.sequence,
                        "kind": event.kind,
                        "message": event.message,
                        "at": event.at.isoformat(),
                        "usage": _usage(event.usage),
                    }
                    for event in events
                ]
            }
        )

    async def stream_progress(request: Request) -> Response:
        principal = await authorize_principal(request)
        task_id = request.path_params["task_id"]
        if await config.store.get(task_id, owner=principal.oid) is None:
            raise HTTPException(status_code=404, detail="background task not found")

        async def events() -> AsyncIterator[str]:
            next_sequence = 0
            while True:
                attempt = await config.store.get(task_id, owner=principal.oid)
                if attempt is None:
                    return
                stored = await config.store.progress(task_id, owner=principal.oid, limit=200)
                for event in stored:
                    if event.sequence < next_sequence:
                        continue
                    payload = {
                        "sequence": event.sequence,
                        "kind": event.kind,
                        "message": event.message,
                        "at": event.at.isoformat(),
                        "usage": _usage(event.usage),
                    }
                    yield f"event: progress\ndata: {json.dumps(payload)}\n\n"
                    next_sequence = event.sequence + 1
                if attempt.status in TERMINAL_BACKGROUND_STATUSES:
                    terminal = {
                        "task_id": task_id,
                        "status": attempt.status.value,
                        "terminal_reason": (
                            attempt.result.terminal_reason if attempt.result is not None else None
                        ),
                    }
                    yield f"event: terminal\ndata: {json.dumps(terminal)}\n\n"
                    return
                yield ": heartbeat\n\n"
                await asyncio.sleep(0.25)

        return StreamingResponse(events(), media_type="text/event-stream")

    async def cancel_task(request: Request) -> Response:
        principal = await authorize_principal(request)
        is_admin = Role.OWNER in principal.roles
        try:
            await config.coordinator.cancel(
                request.path_params["task_id"],
                actor=principal.oid,
                is_admin=is_admin,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="background task not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail="background task not found") from exc
        attempt = await config.store.get(request.path_params["task_id"])
        if attempt is None:
            raise HTTPException(status_code=404, detail="background task not found")
        return JSONResponse(_attempt(attempt))

    return (
        Route("/background-tasks", create_task, methods=["POST"]),
        Route("/background-tasks", list_tasks, methods=["GET"]),
        Route("/background-tasks/{task_id}", get_task, methods=["GET"]),
        Route("/background-tasks/{task_id}/progress", get_progress, methods=["GET"]),
        Route(
            "/background-tasks/{task_id}/progress/stream",
            stream_progress,
            methods=["GET"],
        ),
        Route("/background-tasks/{task_id}/cancel", cancel_task, methods=["POST"]),
    )


async def _body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > _MAX_BODY:
        raise HTTPException(status_code=413, detail="request body exceeds cap")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="request body MUST be JSON") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="request body MUST be an object")
    return value


def _attempt(attempt: BackgroundTaskAttempt, *, include_prompt: bool = True) -> dict[str, Any]:
    task = attempt.task
    payload: dict[str, Any] = {
        "task_id": task.task_id,
        "attempt_id": attempt.attempt_id,
        "status": attempt.status.value,
        "correlation_id": task.correlation_id,
        "origin": {
            "conversation_id": task.origin.conversation_id,
            "channel_kind": task.origin.channel_kind,
            "channel_id": task.origin.channel_id,
            "thread_id": task.origin.thread_id,
        },
        "capability_profile_id": task.capability_profile_id,
        "budget": {
            "max_wall_seconds": task.budget.max_wall_seconds,
            "max_tokens": task.budget.max_tokens,
            "max_cost_microusd": task.budget.max_cost_microusd,
            "max_tool_calls": task.budget.max_tool_calls,
        },
        "usage": _usage(attempt.usage),
        "created_at": task.created_at.isoformat(),
        "updated_at": attempt.updated_at.isoformat(),
        "retention_until": task.retention_until.isoformat(),
        "lease_expires_at": (
            attempt.lease.expires_at.isoformat() if attempt.lease is not None else None
        ),
        "terminal_reason": (attempt.result.terminal_reason if attempt.result is not None else None),
    }
    if include_prompt:
        payload["prompt"] = task.prompt
        payload["result"] = (
            {
                "trusted": False,
                "summary": attempt.result.summary,
                "evidence_refs": list(attempt.result.evidence_refs),
            }
            if attempt.result is not None
            else None
        )
    return payload


def _budget(body: dict[str, Any]) -> BackgroundTaskBudget:
    raw = body.get("budget") or {}
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="budget MUST be an object")
    return BackgroundTaskBudget(
        max_wall_seconds=int(raw.get("max_wall_seconds", 300)),
        max_tokens=int(raw.get("max_tokens", 4_096)),
        max_cost_microusd=int(raw.get("max_cost_microusd", 500_000)),
        max_tool_calls=int(raw.get("max_tool_calls", 8)),
        max_progress_events=int(raw.get("max_progress_events", 32)),
    )


def _usage(usage: Any) -> dict[str, int]:
    return {
        "tokens": int(usage.tokens),
        "cost_microusd": int(usage.cost_microusd),
        "tool_calls": int(usage.tool_calls),
    }


def _string(body: dict[str, Any], key: str, *, maximum: int = 256) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise HTTPException(status_code=400, detail=f"{key} MUST be a bounded string")
    return value.strip()


def _optional_string(body: dict[str, Any], key: str) -> str | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise HTTPException(status_code=400, detail=f"{key} MUST be a bounded string")
    return value.strip()


def _integer(body: dict[str, Any], key: str, *, default: int) -> int:
    value = body.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"{key} MUST be an integer")
    return value


def _query_limit(request: Request) -> int:
    try:
        limit = int(request.query_params.get("limit", "100"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="limit MUST be an integer") from exc
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=400, detail="limit MUST be in [1, 200]")
    return limit


__all__ = ["BackgroundTaskRoutesConfig", "make_background_task_routes"]
