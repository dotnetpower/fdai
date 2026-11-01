"""Owner-scoped read-only Operator materializer for bounded task workers."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from fdai_operator_service.families.conversation.contracts import (
    ConversationBoundaryError,
    ConversationQuery,
    ConversationResponse,
    JsonObject,
    JsonValue,
)

FetchAll = Callable[[str, tuple[object, ...]], Awaitable[Sequence[Mapping[str, Any]]]]
_WORKER_READ_OPERATIONS = frozenset({"workers.list", "workers.get", "workers.events"})
_TERMINAL_SUMMARY_STATUSES = frozenset({"succeeded", "abstained"})


@dataclass(frozen=True, slots=True)
class TaskWorkerEventRecord:
    worker_id: str
    sequence: int
    kind: str
    at: str
    details: tuple[tuple[str, str], ...] = ()

    def to_json(self) -> JsonObject:
        return {
            "worker_id": self.worker_id,
            "sequence": self.sequence,
            "kind": self.kind,
            "at": self.at,
            "details": [[key, value] for key, value in self.details],
        }


@dataclass(frozen=True, slots=True)
class TaskWorkerResultRecord:
    worker_id: str
    parent_trace_ref: str
    status: str
    summary: str | None
    evidence_refs: tuple[str, ...]
    caveats: tuple[str, ...]
    usage: JsonObject
    terminal_reason: str
    started_at: str
    finished_at: str
    trusted: bool = False

    def __post_init__(self) -> None:
        if self.trusted:
            raise ValueError("task worker result projection MUST remain untrusted")

    def to_json(self) -> JsonObject:
        raw_summary = self.summary if self.status in _TERMINAL_SUMMARY_STATUSES else None
        return {
            "worker_id": self.worker_id,
            "parent_trace_ref": self.parent_trace_ref,
            "status": self.status,
            "summary": raw_summary[:2_000] if raw_summary is not None else None,
            "summary_truncated": raw_summary is not None and len(raw_summary) > 2_000,
            "evidence_refs": list(self.evidence_refs),
            "caveats": list(self.caveats),
            "usage": dict(self.usage),
            "terminal_reason": self.terminal_reason,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "trusted": False,
        }


@dataclass(frozen=True, slots=True)
class TaskWorkerSnapshotRecord:
    worker_id: str
    parent_trace_ref: str
    cancellation_owner: str
    status: str
    goal: str
    constraints: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    denied_tools: tuple[str, ...]
    budget: JsonObject
    usage: JsonObject
    created_at: str
    updated_at: str
    heartbeat_at: str | None = None
    result: TaskWorkerResultRecord | None = None

    def to_list_row_json(self) -> JsonObject:
        """List rows omit goal and constraints and expose bounded status, budget, and usage."""
        return {
            "worker_id": self.worker_id,
            "parent_trace_ref": self.parent_trace_ref,
            "status": self.status,
            "budget": dict(self.budget),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "heartbeat_at": self.heartbeat_at,
            "allowed_tools": list(sorted(self.allowed_tools)),
            "denied_tools": list(self.denied_tools),
            "evidence_count": len(self.evidence_refs),
            "usage": dict(self.usage),
            "terminal_reason": self.result.terminal_reason if self.result is not None else None,
            "trusted": False,
            "read_only": True,
            "execution_authority": "none",
        }

    def to_detail_json(self) -> JsonObject:
        detail = self.to_list_row_json()
        detail["evidence_refs"] = list(self.evidence_refs)
        detail["result"] = self.result.to_json() if self.result is not None else None
        return detail


class TaskWorkerProjectionStore(Protocol):
    async def list(self, *, owner: str, limit: int = 100) -> tuple[Any, ...]: ...
    async def get(self, worker_id: str, *, owner: str) -> Any | None: ...
    async def events(self, worker_id: str, *, owner: str, limit: int = 500) -> tuple[Any, ...]: ...


class SqlTaskWorkerProjectionStore:
    def __init__(self, *, fetch_all: FetchAll) -> None:
        self._fetch_all = fetch_all

    async def list(self, *, owner: str, limit: int = 100) -> tuple[TaskWorkerSnapshotRecord, ...]:
        owner_id = _require_owner(owner)
        rows = await self._fetch_all(
            "SELECT worker_id, parent_trace_ref, cancellation_owner, status, request, "
            "capabilities, usage, result, created_at, updated_at, heartbeat_at "
            "FROM task_worker_run WHERE cancellation_owner = %s "
            "ORDER BY updated_at DESC, worker_id DESC LIMIT %s",
            (owner_id, limit),
        )
        return tuple(_snapshot_from_row(row) for row in rows)

    async def get(self, worker_id: str, *, owner: str) -> TaskWorkerSnapshotRecord | None:
        owner_id = _require_owner(owner)
        rows = await self._fetch_all(
            "SELECT worker_id, parent_trace_ref, cancellation_owner, status, request, "
            "capabilities, usage, result, created_at, updated_at, heartbeat_at "
            "FROM task_worker_run WHERE worker_id = %s AND cancellation_owner = %s",
            (worker_id, owner_id),
        )
        return _snapshot_from_row(rows[0]) if rows else None

    async def events(
        self, worker_id: str, *, owner: str, limit: int = 500
    ) -> tuple[TaskWorkerEventRecord, ...]:
        owner_id = _require_owner(owner)
        rows = await self._fetch_all(
            "SELECT worker_id, sequence, kind, at, details FROM task_worker_event "
            "WHERE worker_id = %s AND EXISTS (SELECT 1 FROM task_worker_run run "
            "WHERE run.worker_id = task_worker_event.worker_id AND run.cancellation_owner = %s) "
            "ORDER BY sequence DESC LIMIT %s",
            (worker_id, owner_id, limit),
        )
        if not rows and await self.get(worker_id, owner=owner_id) is None:
            raise LookupError(f"task worker {worker_id!r} was not found")
        return tuple(_event_from_row(row) for row in reversed(list(rows)))


class TaskWorkerProjectionMaterializer:
    def __init__(self, *, store: TaskWorkerProjectionStore) -> None:
        self._store = store

    async def read(self, query: ConversationQuery) -> ConversationResponse:
        if query.operation not in _WORKER_READ_OPERATIONS:
            raise ConversationBoundaryError(
                400, "unsupported_worker_operation", f"unsupported operation {query.operation}"
            )
        owner = _require_owner(query.scope.subject_id)
        if query.operation == "workers.list":
            limit = _bounded_int(query.query.get("limit"), default=50, minimum=1, maximum=100)
            snapshots = await self._store.list(owner=owner, limit=limit)
            workers: list[JsonValue] = [
                _coerce_snapshot(item).to_list_row_json() for item in snapshots
            ]
            return ConversationResponse(
                body={"read_only": True, "execution_authority": "none", "workers": workers},
                status_code=200,
            )

        worker_id = _worker_id(query.path_params)
        if query.operation == "workers.get":
            snapshot = await self._store.get(worker_id, owner=owner)
            if snapshot is None:
                return _not_found_response(worker_id)
            return ConversationResponse(
                body={
                    "read_only": True,
                    "execution_authority": "none",
                    "worker": _coerce_snapshot(snapshot).to_detail_json(),
                },
                status_code=200,
            )

        limit = _bounded_int(query.query.get("limit"), default=100, minimum=1, maximum=500)
        try:
            events_raw = await self._store.events(worker_id, owner=owner, limit=limit)
        except LookupError:
            return _not_found_response(worker_id)
        events: list[JsonValue] = [_coerce_event(item).to_json() for item in events_raw]
        return ConversationResponse(
            body={
                "read_only": True,
                "execution_authority": "none",
                "worker_id": worker_id,
                "events": events,
            },
            status_code=200,
        )


def _not_found_response(worker_id: str) -> ConversationResponse:
    return ConversationResponse(
        body={
            "read_only": True,
            "execution_authority": "none",
            "error": {
                "code": "task_worker_not_found",
                "message": "task worker not found",
                "worker_id": worker_id,
            },
        },
        status_code=404,
    )


def _require_owner(owner: str) -> str:
    cleaned = owner.strip()
    if not cleaned:
        raise ConversationBoundaryError(
            401, "unauthenticated", "authenticated owner principal is required"
        )
    return cleaned


def _worker_id(path_params: JsonObject) -> str:
    raw = path_params.get("worker_id")
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 256:
        raise ConversationBoundaryError(400, "invalid_worker_id", "worker_id MUST be bounded")
    return raw.strip()


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ConversationBoundaryError(400, "invalid_limit", "limit MUST be an integer")
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConversationBoundaryError(400, "invalid_limit", "limit MUST be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ConversationBoundaryError(400, "invalid_limit", "limit is out of bounds")
    return parsed


def _iso(value: object) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _coerce_snapshot(item: Any) -> TaskWorkerSnapshotRecord:
    if isinstance(item, TaskWorkerSnapshotRecord):
        return item
    req, caps, b = item.request, item.capabilities, item.request.budget
    res = item.result
    return _snapshot_from_row(
        {
            "worker_id": req.worker_id,
            "parent_trace_ref": req.parent_trace_ref,
            "cancellation_owner": req.cancellation_owner,
            "status": getattr(item.status, "value", item.status),
            "request": {
                "goal": req.goal,
                "constraints": list(req.constraints),
                "evidence_refs": list(req.evidence_refs),
                "budget": {
                    "max_wall_seconds": float(b.max_wall_seconds),
                    "max_tool_calls": int(b.max_tool_calls),
                    "max_tokens": int(b.max_tokens),
                    "max_cost_microusd": int(b.max_cost_microusd),
                    "heartbeat_seconds": float(b.heartbeat_seconds),
                },
            },
            "capabilities": {
                "allowed_tools": list(sorted(caps.allowed_tools)),
                "denied_tools": list(caps.denied_tools),
            },
            "usage": item.usage.to_dict() if hasattr(item.usage, "to_dict") else dict(item.usage),
            "result": (
                {
                    "worker_id": res.worker_id,
                    "parent_trace_ref": res.parent_trace_ref,
                    "status": getattr(res.status, "value", res.status),
                    "summary": res.summary,
                    "evidence_refs": list(res.evidence_refs),
                    "caveats": list(res.caveats),
                    "usage": (
                        res.usage.to_dict() if hasattr(res.usage, "to_dict") else dict(res.usage)
                    ),
                    "terminal_reason": res.terminal_reason,
                    "started_at": res.started_at,
                    "finished_at": res.finished_at,
                    "trusted": res.trusted,
                }
                if res is not None
                else None
            ),
            "created_at": req.created_at,
            "updated_at": item.updated_at,
            "heartbeat_at": item.heartbeat_at,
        }
    )


def _coerce_event(item: Any) -> TaskWorkerEventRecord:
    if isinstance(item, TaskWorkerEventRecord):
        return item
    return TaskWorkerEventRecord(
        str(item.worker_id),
        int(item.sequence),
        str(item.kind),
        _iso(item.at),
        tuple((str(k), str(v)) for k, v in item.details),
    )


def _snapshot_from_row(row: Mapping[str, Any]) -> TaskWorkerSnapshotRecord:
    req, caps, usage = (
        _json_obj(row["request"]),
        _json_obj(row["capabilities"]),
        _json_obj(row["usage"]),
    )
    res = _json_obj(row["result"]) if row.get("result") is not None else None
    result_rec = (
        TaskWorkerResultRecord(
            str(res["worker_id"]),
            str(res["parent_trace_ref"]),
            str(res["status"]),
            str(res["summary"]) if res.get("summary") is not None else None,
            tuple(str(x) for x in _json_list(res.get("evidence_refs", []))),
            tuple(str(x) for x in _json_list(res.get("caveats", []))),
            _json_obj(res.get("usage", {})),
            str(res["terminal_reason"]),
            _iso(res["started_at"]),
            _iso(res["finished_at"]),
            bool(res.get("trusted", False)),
        )
        if res is not None
        else None
    )
    hb = _iso(row["heartbeat_at"]) if row.get("heartbeat_at") is not None else None
    return TaskWorkerSnapshotRecord(
        str(row["worker_id"]),
        str(row["parent_trace_ref"]),
        str(row["cancellation_owner"]),
        str(row["status"]),
        str(req.get("goal", "")),
        tuple(str(x) for x in _json_list(req.get("constraints", []))),
        tuple(str(x) for x in _json_list(req.get("evidence_refs", []))),
        tuple(str(x) for x in _json_list(caps.get("allowed_tools", []))),
        tuple(str(x) for x in _json_list(caps.get("denied_tools", []))),
        _json_obj(req.get("budget", {})),
        usage,
        _iso(row["created_at"]),
        _iso(row["updated_at"]),
        hb,
        result_rec,
    )


def _event_from_row(row: Mapping[str, Any]) -> TaskWorkerEventRecord:
    details = tuple(
        (str(p[0]), str(p[1]))
        for p in _json_list(row.get("details", []))
        if isinstance(p, (list, tuple)) and len(p) == 2
    )
    return TaskWorkerEventRecord(
        str(row["worker_id"]), int(row["sequence"]), str(row["kind"]), _iso(row["at"]), details
    )


def _json_obj(value: Any) -> dict[str, Any]:
    data = json.loads(value) if isinstance(value, str) else value
    return dict(data) if isinstance(data, Mapping) else {}


def _json_list(value: Any) -> list[Any]:
    data = json.loads(value) if isinstance(value, str) else value
    return list(data) if isinstance(data, (list, tuple)) else []
