"""Owner-scoped read projections for durable background tasks."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai_operator_service.families.conversation.contracts import (
    ConversationBoundaryError,
    ConversationEventStream,
    ConversationQuery,
    ConversationResponse,
    ConversationStreamRequest,
    JsonObject,
    StreamEvent,
)

_READ_OPERATIONS = frozenset({"background.list", "background.get", "background.progress"})
_EXECUTION_WORKER = "background-task-coordinator"
_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "timed_out", "unknown"})


@dataclass(frozen=True, slots=True)
class BackgroundTaskProjection:
    """Bounded task fields safe for the owning operator to inspect."""

    task_id: str
    attempt_id: str
    kind: str
    status: str
    revision: int
    created_at: datetime
    updated_at: datetime
    retention_until: datetime
    budget: JsonObject
    usage: JsonObject
    lease_expires_at: datetime | None = None
    terminal_reason: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    completion_state: str | None = None
    request_summary: str | None = None
    request_truncated: bool = False
    accountable_agent: str | None = None
    result_summary: str | None = None
    result_truncated: bool = False
    evidence_refs: tuple[str, ...] = ()
    evidence_truncated: bool = False


@dataclass(frozen=True, slots=True)
class BackgroundTaskProgressProjection:
    """One bounded monotonic progress event for an authorized task."""

    sequence: int
    kind: str
    message: str
    at: datetime
    usage: JsonObject


class BackgroundTaskProjectionStore(Protocol):
    """Read only the task rows owned by one authenticated principal."""

    async def list_background_tasks(
        self,
        *,
        owner_principal_id: str,
        before_updated_at: datetime | None,
        before_task_id: str | None,
        limit: int,
    ) -> tuple[BackgroundTaskProjection, ...]: ...

    async def read_background_task(
        self,
        *,
        owner_principal_id: str,
        task_id: str,
    ) -> BackgroundTaskProjection | None: ...

    async def read_background_task_progress(
        self,
        *,
        owner_principal_id: str,
        task_id: str,
        after_sequence: int,
        limit: int,
    ) -> tuple[BackgroundTaskProgressProjection, ...]: ...


async def materialize_background_task(
    query: ConversationQuery,
    *,
    store: BackgroundTaskProjectionStore,
) -> ConversationResponse | None:
    """Materialize one recognized background-task read without widening scope."""

    if query.operation not in _READ_OPERATIONS:
        return None
    if query.operation == "background.list":
        return await _list_response(query, store=store)
    task_id = _task_id(query.path_params)
    task = await store.read_background_task(
        owner_principal_id=query.scope.subject_id,
        task_id=task_id,
    )
    if task is None:
        raise _not_found()
    if query.operation == "background.get":
        return ConversationResponse(body={"task": _task_json(task)})
    after_sequence = _integer_query(query.query, "after", default=-1, minimum=-1, maximum=2**31)
    limit = _integer_query(query.query, "limit", default=100, minimum=1, maximum=256)
    progress_rows = await store.read_background_task_progress(
        owner_principal_id=query.scope.subject_id,
        task_id=task_id,
        after_sequence=after_sequence,
        limit=limit + 1 if limit < 256 else limit,
    )
    progress = progress_rows[:limit]
    has_more = len(progress_rows) > limit
    return ConversationResponse(
        body={
            "task_id": task_id,
            "status": task.status,
            "events": [_progress_json(item) for item in progress],
            "next_sequence": progress[-1].sequence if progress else after_sequence,
            "has_more": has_more,
        }
    )


async def open_background_task_stream(
    request: ConversationStreamRequest,
    *,
    store: BackgroundTaskProjectionStore,
) -> ConversationEventStream | None:
    """Open a finite owner-scoped progress replay ending in terminal state or heartbeat."""

    if request.operation != "background.progress_stream":
        return None
    task_id = _task_id(request.path_params)
    task = await store.read_background_task(
        owner_principal_id=request.scope.subject_id,
        task_id=task_id,
    )
    if task is None:
        raise _not_found()
    terminal_event_id = f"{task.attempt_id}:terminal"
    if request.after_event_id == terminal_event_id:
        return _BackgroundTaskEventIterator(())
    after_sequence = _integer_value(
        request.after_event_id,
        "Last-Event-ID",
        default=-1,
        minimum=-1,
        maximum=2**31,
    )
    progress_rows = await store.read_background_task_progress(
        owner_principal_id=request.scope.subject_id,
        task_id=task_id,
        after_sequence=after_sequence,
        limit=101,
    )
    progress = progress_rows[:100]
    has_more = len(progress_rows) > 100
    events = [
        StreamEvent(
            event="progress",
            event_id=str(item.sequence),
            data=_progress_json(item),
        )
        for item in progress
    ]
    if task.status in _TERMINAL_STATUSES and not has_more:
        events.append(
            StreamEvent(
                event="terminal",
                event_id=terminal_event_id,
                data={
                    "task_id": task.task_id,
                    "status": task.status,
                    "terminal_reason": task.terminal_reason,
                },
            )
        )
    elif not events:
        events.append(
            StreamEvent(
                event="heartbeat",
                data={"task_id": task.task_id, "status": task.status},
                retry_ms=1_000,
            )
        )
    return _BackgroundTaskEventIterator(tuple(events))


async def _list_response(
    query: ConversationQuery,
    *,
    store: BackgroundTaskProjectionStore,
) -> ConversationResponse:
    limit = _integer_query(query.query, "limit", default=50, minimum=1, maximum=100)
    raw_updated_at = query.query.get("before_updated_at")
    raw_task_id = query.query.get("before_task_id")
    if (raw_updated_at is None) != (raw_task_id is None):
        raise _invalid("background task cursor MUST be complete")
    before_updated_at = None
    before_task_id = None
    if raw_updated_at is not None and raw_task_id is not None:
        if not isinstance(raw_updated_at, str) or not isinstance(raw_task_id, str):
            raise _invalid("background task cursor MUST contain strings")
        try:
            before_updated_at = datetime.fromisoformat(raw_updated_at)
        except ValueError as exc:
            raise _invalid("background task cursor timestamp is invalid") from exc
        if before_updated_at.tzinfo is None:
            raise _invalid("background task cursor timestamp MUST be timezone-aware")
        before_task_id = _identifier("before_task_id", raw_task_id)
    rows = await store.list_background_tasks(
        owner_principal_id=query.scope.subject_id,
        before_updated_at=before_updated_at,
        before_task_id=before_task_id,
        limit=limit + 1,
    )
    page = rows[:limit]
    has_more = len(rows) > limit
    cursor: JsonObject | None = None
    if has_more and page:
        cursor = {
            "before_updated_at": page[-1].updated_at.isoformat(),
            "before_task_id": page[-1].task_id,
        }
    return ConversationResponse(
        body={
            "tasks": [_task_json(item) for item in page],
            "has_more": has_more,
            "next_cursor": cursor,
        }
    )


def _task_json(task: BackgroundTaskProjection) -> JsonObject:
    duration_seconds = None
    if task.started_at is not None and task.finished_at is not None:
        duration_seconds = max(0.0, (task.finished_at - task.started_at).total_seconds())
    return {
        "task_id": task.task_id,
        "attempt_id": task.attempt_id,
        "request_summary": task.request_summary,
        "request_truncated": task.request_truncated,
        "accountable_agent": task.accountable_agent,
        "execution_worker": _EXECUTION_WORKER,
        "kind": task.kind,
        "status": task.status,
        "revision": task.revision,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "retention_until": task.retention_until.isoformat(),
        "lease_expires_at": (
            task.lease_expires_at.isoformat() if task.lease_expires_at is not None else None
        ),
        "budget": task.budget,
        "usage": task.usage,
        "result_summary": task.result_summary,
        "result_truncated": task.result_truncated,
        "evidence_refs": list(task.evidence_refs),
        "evidence_truncated": task.evidence_truncated,
        "terminal_reason": task.terminal_reason,
        "started_at": task.started_at.isoformat() if task.started_at is not None else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at is not None else None,
        "duration_seconds": duration_seconds,
        "completion_state": task.completion_state,
    }


def _progress_json(progress: BackgroundTaskProgressProjection) -> JsonObject:
    return {
        "sequence": progress.sequence,
        "kind": progress.kind,
        "message": progress.message,
        "at": progress.at.isoformat(),
        "usage": progress.usage,
    }


def _task_id(path_params: JsonObject) -> str:
    value = path_params.get("task_id")
    if not isinstance(value, str):
        raise _invalid("task_id MUST be a string")
    return _identifier("task_id", value)


def _identifier(name: str, value: str) -> str:
    if not value.strip() or len(value) > 256 or any(ord(char) < 32 for char in value):
        raise _invalid(f"{name} MUST be a bounded identifier")
    return value


def _integer_query(
    query: JsonObject,
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    return _integer_value(
        query.get(name),
        name,
        default=default,
        minimum=minimum,
        maximum=maximum,
    )


def _integer_value(
    value: object,
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise _invalid(f"{name} MUST be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{name} MUST be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise _invalid(f"{name} is outside the bounded range")
    return parsed


def _not_found() -> ConversationBoundaryError:
    return ConversationBoundaryError(404, "not_found", "background task is unavailable")


def _invalid(message: str) -> ConversationBoundaryError:
    return ConversationBoundaryError(400, "invalid_request", message)


class _BackgroundTaskEventIterator(AsyncIterator[StreamEvent]):
    def __init__(self, events: tuple[StreamEvent, ...]) -> None:
        self._events = iter(events)

    def __aiter__(self) -> _BackgroundTaskEventIterator:
        return self

    async def __anext__(self) -> StreamEvent:
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def aclose(self) -> None:
        """Close the finite task replay iterator."""


__all__ = [
    "BackgroundTaskProgressProjection",
    "BackgroundTaskProjection",
    "BackgroundTaskProjectionStore",
    "materialize_background_task",
    "open_background_task_stream",
]
