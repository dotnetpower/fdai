"""Principal-scoped read-only projections for isolated task workers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.task_worker import TaskWorkerEvent, TaskWorkerSnapshot, TaskWorkerStore

AuthorizeFn = Callable[[Request], Awaitable[str]]


def make_task_worker_routes(
    *,
    store: TaskWorkerStore,
    authorize: AuthorizeFn,
) -> tuple[Route, ...]:
    async def list_workers(request: Request) -> Response:
        owner = await authorize(request)
        limit = _limit(request, default=100, maximum=200)
        snapshots = await store.list(owner=owner, limit=limit)
        return JSONResponse(
            {"workers": [_snapshot(item, include_result=False) for item in snapshots]}
        )

    async def get_worker(request: Request) -> Response:
        owner = await authorize(request)
        snapshot = await store.get(request.path_params["worker_id"], owner=owner)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="task worker not found")
        return JSONResponse(_snapshot(snapshot, include_result=True))

    async def list_events(request: Request) -> Response:
        owner = await authorize(request)
        worker_id = request.path_params["worker_id"]
        limit = _limit(request, default=500, maximum=1_000)
        try:
            events = await store.events(worker_id, owner=owner, limit=limit)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="task worker not found") from exc
        return JSONResponse({"events": [_event(item) for item in events]})

    return (
        Route("/task-workers", list_workers, methods=["GET"]),
        Route("/task-workers/{worker_id}", get_worker, methods=["GET"]),
        Route("/task-workers/{worker_id}/events", list_events, methods=["GET"]),
    )


def _snapshot(snapshot: TaskWorkerSnapshot, *, include_result: bool) -> dict[str, Any]:
    request = snapshot.request
    result = snapshot.result
    payload: dict[str, Any] = {
        "worker_id": request.worker_id,
        "parent_trace_ref": request.parent_trace_ref,
        "status": snapshot.status.value,
        "created_at": request.created_at.isoformat(),
        "updated_at": snapshot.updated_at.isoformat(),
        "heartbeat_at": (
            snapshot.heartbeat_at.isoformat() if snapshot.heartbeat_at is not None else None
        ),
        "budget": {
            "max_wall_seconds": request.budget.max_wall_seconds,
            "max_tool_calls": request.budget.max_tool_calls,
            "max_tokens": request.budget.max_tokens,
            "max_cost_microusd": request.budget.max_cost_microusd,
            "heartbeat_seconds": request.budget.heartbeat_seconds,
        },
        "usage": {
            "tokens": snapshot.usage.tokens,
            "cost_microusd": snapshot.usage.cost_microusd,
            "tool_calls": snapshot.usage.tool_calls,
        },
        "tools": {
            "requested": sorted(request.requested_tools),
            "allowed": sorted(snapshot.capabilities.allowed_tools),
            "denied": list(snapshot.capabilities.denied_tools),
        },
        "evidence_count": len(
            result.evidence_refs if result is not None else request.evidence_refs
        ),
        "terminal_reason": result.terminal_reason if result is not None else None,
    }
    if include_result and result is not None:
        payload["result"] = {
            "trusted": False,
            "summary": result.summary,
            "evidence_refs": list(result.evidence_refs),
            "caveats": list(result.caveats),
            "terminal_reason": result.terminal_reason,
            "started_at": result.started_at.isoformat(),
            "finished_at": result.finished_at.isoformat(),
        }
    return payload


def _event(event: TaskWorkerEvent) -> dict[str, Any]:
    return {
        "sequence": event.sequence,
        "kind": event.kind,
        "at": event.at.isoformat(),
        "details": dict(event.details),
    }


def _limit(request: Request, *, default: int, maximum: int) -> int:
    raw = request.query_params.get("limit", str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="limit MUST be an integer") from exc
    if not 1 <= value <= maximum:
        raise HTTPException(status_code=400, detail=f"limit MUST be in [1, {maximum}]")
    return value


__all__ = ["make_task_worker_routes"]
