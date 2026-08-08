"""PostgreSQL lifecycle and branch-event store for isolated task workers."""

# ruff: noqa: S608 - interpolated identifiers are module constants; values are bound.

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.core.task_worker import (
    AttenuatedCapabilities,
    TaskWorkerBudget,
    TaskWorkerConflictError,
    TaskWorkerEvent,
    TaskWorkerRequest,
    TaskWorkerResult,
    TaskWorkerSnapshot,
    TaskWorkerStatus,
    TaskWorkerUsage,
)

_COLUMNS: Final = (
    "worker_id, parent_trace_ref, cancellation_owner, status, request, capabilities, "
    "usage, result, created_at, updated_at, heartbeat_at"
)


@dataclass(frozen=True, slots=True)
class PostgresTaskWorkerStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresTaskWorkerStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresTaskWorkerStoreConfig timeouts MUST be positive")


class PostgresTaskWorkerStore:
    def __init__(self, *, config: PostgresTaskWorkerStoreConfig) -> None:
        self._config = config

    async def create(self, snapshot: TaskWorkerSnapshot) -> tuple[TaskWorkerSnapshot, bool]:
        request = snapshot.request
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                f"INSERT INTO task_worker_run ({_COLUMNS}) "
                "VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, NULL, "
                "%s, %s, %s) ON CONFLICT (worker_id) DO NOTHING "
                f"RETURNING {_COLUMNS}",  # noqa: S608 - fixed column constant
                (
                    request.worker_id,
                    request.parent_trace_ref,
                    request.cancellation_owner,
                    snapshot.status.value,
                    json.dumps(_request_to_dict(request)),
                    json.dumps(_capabilities_to_dict(snapshot.capabilities)),
                    json.dumps(_usage_to_dict(snapshot.usage)),
                    request.created_at,
                    snapshot.updated_at,
                    snapshot.heartbeat_at,
                ),
            )
            row = await cursor.fetchone()
            created = row is not None
            if row is None:
                existing = await connection.execute(
                    f"SELECT {_COLUMNS} FROM task_worker_run WHERE worker_id = %s",  # noqa: S608
                    (request.worker_id,),
                )
                row = await existing.fetchone()
        if row is None:
            raise RuntimeError("task worker insert returned no row")
        prior = _snapshot(row)
        if prior.request != request:
            raise TaskWorkerConflictError("worker id reused with another request")
        return prior, created

    async def get(
        self,
        worker_id: str,
        *,
        owner: str | None = None,
    ) -> TaskWorkerSnapshot | None:
        owner_clause = " AND cancellation_owner = %s" if owner is not None else ""
        params: tuple[object, ...] = (worker_id, owner) if owner is not None else (worker_id,)
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM task_worker_run WHERE worker_id = %s{owner_clause}",
                params,
            )
            row = await cursor.fetchone()
        return _snapshot(row) if row is not None else None

    async def transition(
        self,
        worker_id: str,
        *,
        expected: frozenset[TaskWorkerStatus],
        status: TaskWorkerStatus,
        usage: TaskWorkerUsage,
        at: datetime,
        result: TaskWorkerResult | None = None,
    ) -> TaskWorkerSnapshot:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "UPDATE task_worker_run SET status = %s, usage = %s::jsonb, "
                "result = %s::jsonb, updated_at = %s, revision = revision + 1 "
                "WHERE worker_id = %s AND status = ANY(%s) "
                f"RETURNING {_COLUMNS}",  # noqa: S608 - fixed column constant
                (
                    status.value,
                    json.dumps(_usage_to_dict(usage)),
                    json.dumps(_result_to_dict(result)) if result is not None else None,
                    at,
                    worker_id,
                    [item.value for item in expected],
                ),
            )
            row = await cursor.fetchone()
        if row is None:
            current = await self.get(worker_id)
            if current is None:
                raise LookupError(f"task worker {worker_id!r} was not found")
            raise TaskWorkerConflictError(f"worker status conflict: current={current.status.value}")
        return _snapshot(row)

    async def heartbeat(
        self,
        worker_id: str,
        *,
        usage: TaskWorkerUsage,
        at: datetime,
    ) -> TaskWorkerSnapshot:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "UPDATE task_worker_run SET usage = %s::jsonb, heartbeat_at = %s, "
                "updated_at = %s, revision = revision + 1 "
                "WHERE worker_id = %s AND status = 'running' "
                f"RETURNING {_COLUMNS}",  # noqa: S608 - fixed column constant
                (json.dumps(_usage_to_dict(usage)), at, at, worker_id),
            )
            row = await cursor.fetchone()
        if row is not None:
            return _snapshot(row)
        current = await self.get(worker_id)
        if current is None:
            raise LookupError(f"task worker {worker_id!r} was not found")
        return current

    async def append_event(
        self,
        worker_id: str,
        *,
        kind: str,
        at: datetime,
        details: tuple[tuple[str, str], ...] = (),
    ) -> TaskWorkerEvent:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            locked = await connection.execute(
                "SELECT worker_id FROM task_worker_run WHERE worker_id = %s FOR UPDATE",
                (worker_id,),
            )
            if await locked.fetchone() is None:
                raise LookupError(f"task worker {worker_id!r} was not found")
            next_sequence = await connection.execute(
                "SELECT COALESCE(MAX(sequence), -1) + 1 AS sequence "
                "FROM task_worker_event WHERE worker_id = %s",
                (worker_id,),
            )
            row = await next_sequence.fetchone()
            if row is None:
                raise RuntimeError("task worker event sequence query returned no row")
            sequence = int(row["sequence"])
            await connection.execute(
                "INSERT INTO task_worker_event (worker_id, sequence, kind, at, details) "
                "VALUES (%s, %s, %s, %s, %s::jsonb)",
                (worker_id, sequence, kind, at, json.dumps(list(details))),
            )
        return TaskWorkerEvent(worker_id, sequence, kind, at, details)

    async def list(
        self,
        *,
        owner: str | None = None,
        limit: int = 100,
    ) -> tuple[TaskWorkerSnapshot, ...]:
        _limit(limit, 1_000)
        owner_clause = "WHERE cancellation_owner = %s " if owner is not None else ""
        params: tuple[object, ...] = (owner, limit) if owner is not None else (limit,)
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM task_worker_run "
                f"{owner_clause}ORDER BY updated_at DESC, worker_id DESC LIMIT %s",
                params,
            )
            rows = await cursor.fetchall()
        return tuple(_snapshot(row) for row in rows)

    async def events(
        self,
        worker_id: str,
        *,
        owner: str | None = None,
        limit: int = 500,
    ) -> tuple[TaskWorkerEvent, ...]:
        _limit(limit, 5_000)
        owner_clause = (
            " AND EXISTS (SELECT 1 FROM task_worker_run run "
            "WHERE run.worker_id = task_worker_event.worker_id "
            "AND run.cancellation_owner = %s)"
            if owner is not None
            else ""
        )
        params: tuple[object, ...] = (
            (worker_id, owner, limit) if owner is not None else (worker_id, limit)
        )
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT worker_id, sequence, kind, at, details FROM task_worker_event "
                f"WHERE worker_id = %s{owner_clause} "
                "ORDER BY sequence DESC LIMIT %s",
                params,
            )
            rows = list(await cursor.fetchall())
        if owner is not None and not rows and await self.get(worker_id, owner=owner) is None:
            raise LookupError(f"task worker {worker_id!r} was not found")
        rows.reverse()
        return tuple(_event(row) for row in rows)

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _snapshot(row: dict[str, Any]) -> TaskWorkerSnapshot:
    request = _request(_mapping(row["request"]))
    result_raw = row["result"]
    return TaskWorkerSnapshot(
        request=request,
        capabilities=_capabilities(_mapping(row["capabilities"])),
        status=TaskWorkerStatus(str(row["status"])),
        usage=_usage(_mapping(row["usage"])),
        updated_at=row["updated_at"],
        heartbeat_at=row["heartbeat_at"],
        result=(_result(_mapping(result_raw)) if result_raw is not None else None),
    )


def _event(row: dict[str, Any]) -> TaskWorkerEvent:
    details_raw = row["details"]
    if isinstance(details_raw, str):
        details_raw = json.loads(details_raw)
    details = tuple(
        (str(item[0]), str(item[1]))
        for item in details_raw
        if isinstance(item, list) and len(item) == 2
    )
    return TaskWorkerEvent(
        worker_id=str(row["worker_id"]),
        sequence=int(row["sequence"]),
        kind=str(row["kind"]),
        at=row["at"],
        details=details,
    )


def _request_to_dict(value: TaskWorkerRequest) -> dict[str, Any]:
    return {
        "worker_id": value.worker_id,
        "parent_trace_ref": value.parent_trace_ref,
        "cancellation_owner": value.cancellation_owner,
        "goal": value.goal,
        "evidence_refs": list(value.evidence_refs),
        "constraints": list(value.constraints),
        "requested_tools": sorted(value.requested_tools),
        "budget": {
            "max_wall_seconds": value.budget.max_wall_seconds,
            "max_tool_calls": value.budget.max_tool_calls,
            "max_tokens": value.budget.max_tokens,
            "max_cost_microusd": value.budget.max_cost_microusd,
            "heartbeat_seconds": value.budget.heartbeat_seconds,
        },
        "created_at": value.created_at.isoformat(),
        "depth": value.depth,
    }


def _request(raw: dict[str, Any]) -> TaskWorkerRequest:
    budget = _mapping(raw["budget"])
    return TaskWorkerRequest(
        worker_id=str(raw["worker_id"]),
        parent_trace_ref=str(raw["parent_trace_ref"]),
        cancellation_owner=str(raw["cancellation_owner"]),
        goal=str(raw["goal"]),
        evidence_refs=tuple(str(item) for item in raw["evidence_refs"]),
        constraints=tuple(str(item) for item in raw["constraints"]),
        requested_tools=frozenset(str(item) for item in raw["requested_tools"]),
        budget=TaskWorkerBudget(
            max_wall_seconds=float(budget["max_wall_seconds"]),
            max_tool_calls=int(budget["max_tool_calls"]),
            max_tokens=int(budget["max_tokens"]),
            max_cost_microusd=int(budget["max_cost_microusd"]),
            heartbeat_seconds=float(budget["heartbeat_seconds"]),
        ),
        created_at=datetime.fromisoformat(str(raw["created_at"])),
        depth=int(raw["depth"]),
    )


def _capabilities_to_dict(value: AttenuatedCapabilities) -> dict[str, Any]:
    return {
        "allowed_tools": sorted(value.allowed_tools),
        "denied_tools": list(value.denied_tools),
    }


def _capabilities(raw: dict[str, Any]) -> AttenuatedCapabilities:
    return AttenuatedCapabilities(
        allowed_tools=frozenset(str(item) for item in raw["allowed_tools"]),
        denied_tools=tuple(str(item) for item in raw["denied_tools"]),
    )


def _usage_to_dict(value: TaskWorkerUsage) -> dict[str, int]:
    return {
        "tokens": value.tokens,
        "cost_microusd": value.cost_microusd,
        "tool_calls": value.tool_calls,
    }


def _usage(raw: dict[str, Any]) -> TaskWorkerUsage:
    return TaskWorkerUsage(
        tokens=int(raw["tokens"]),
        cost_microusd=int(raw["cost_microusd"]),
        tool_calls=int(raw["tool_calls"]),
    )


def _result_to_dict(value: TaskWorkerResult) -> dict[str, Any]:
    return {
        "worker_id": value.worker_id,
        "parent_trace_ref": value.parent_trace_ref,
        "status": value.status.value,
        "summary": value.summary,
        "evidence_refs": list(value.evidence_refs),
        "caveats": list(value.caveats),
        "usage": _usage_to_dict(value.usage),
        "terminal_reason": value.terminal_reason,
        "started_at": value.started_at.isoformat(),
        "finished_at": value.finished_at.isoformat(),
        "trusted": value.trusted,
    }


def _result(raw: dict[str, Any]) -> TaskWorkerResult:
    summary = raw.get("summary")
    return TaskWorkerResult(
        worker_id=str(raw["worker_id"]),
        parent_trace_ref=str(raw["parent_trace_ref"]),
        status=TaskWorkerStatus(str(raw["status"])),
        summary=str(summary) if summary is not None else None,
        evidence_refs=tuple(str(item) for item in raw["evidence_refs"]),
        caveats=tuple(str(item) for item in raw["caveats"]),
        usage=_usage(_mapping(raw["usage"])),
        terminal_reason=str(raw["terminal_reason"]),
        started_at=datetime.fromisoformat(str(raw["started_at"])),
        finished_at=datetime.fromisoformat(str(raw["finished_at"])),
        trusted=bool(raw["trusted"]),
    )


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            return decoded
    raise RuntimeError("task worker JSON column is not an object")


def _limit(value: int, maximum: int) -> None:
    if not 1 <= value <= maximum:
        raise ValueError(f"limit MUST be in [1, {maximum}]")


__all__ = ["PostgresTaskWorkerStore", "PostgresTaskWorkerStoreConfig"]
