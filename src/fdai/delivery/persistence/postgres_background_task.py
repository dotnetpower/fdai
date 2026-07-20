"""PostgreSQL store for durable detached background task attempts."""

# ruff: noqa: S608 - interpolated identifiers are module constants; values are bound.

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.core.background_task import (
    TERMINAL_BACKGROUND_STATUSES,
    BackgroundTask,
    BackgroundTaskAttempt,
    BackgroundTaskBudget,
    BackgroundTaskConflictError,
    BackgroundTaskKind,
    BackgroundTaskLease,
    BackgroundTaskOrigin,
    BackgroundTaskProgress,
    BackgroundTaskResult,
    BackgroundTaskStatus,
    BackgroundTaskUsage,
)

_ATTEMPT_COLUMNS: Final = (
    "attempt_id, task_id, owner_principal_id, idempotency_key, task, "
    "attempt_number, status, revision, created_at, retention_until, updated_at, "
    "max_progress_events, lease_owner, lease_token, lease_expires_at, usage, "
    "result, parent_attempt_id"
)
_PROGRESS_COLUMNS: Final = "attempt_id, sequence, kind, message, at, usage"


@dataclass(frozen=True, slots=True)
class PostgresBackgroundTaskStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresBackgroundTaskStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresBackgroundTaskStoreConfig timeouts MUST be positive")


class PostgresBackgroundTaskStore:
    def __init__(self, *, config: PostgresBackgroundTaskStoreConfig) -> None:
        self._config = config

    async def create(self, task: BackgroundTask) -> tuple[BackgroundTaskAttempt, bool]:
        attempt_id = f"{task.task_id}:1"
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "INSERT INTO background_task_attempt ("
                f"{_ATTEMPT_COLUMNS}) VALUES ("
                "%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, "
                "%s, %s, %s, %s::jsonb, %s::jsonb, %s) "
                "ON CONFLICT DO NOTHING "
                f"RETURNING {_ATTEMPT_COLUMNS}",
                (
                    attempt_id,
                    task.task_id,
                    task.owner_principal_id,
                    task.idempotency_key,
                    json.dumps(_task_to_dict(task)),
                    1,
                    BackgroundTaskStatus.QUEUED.value,
                    1,
                    task.created_at,
                    task.retention_until,
                    task.created_at,
                    task.budget.max_progress_events,
                    None,
                    None,
                    None,
                    json.dumps(_usage_to_dict(BackgroundTaskUsage())),
                    None,
                    None,
                ),
            )
            row = await cursor.fetchone()
            created = row is not None
            if row is None:
                existing = await connection.execute(
                    f"SELECT {_ATTEMPT_COLUMNS} FROM background_task_attempt "
                    "WHERE task_id = %s OR "
                    "(owner_principal_id = %s AND idempotency_key = %s) "
                    "FOR UPDATE",
                    (task.task_id, task.owner_principal_id, task.idempotency_key),
                )
                rows = await existing.fetchall()
                if len(rows) != 1:
                    raise BackgroundTaskConflictError(
                        "background task id or idempotency key conflict"
                    )
                row = rows[0]
        attempt = _attempt(row)
        if attempt.task != task:
            raise BackgroundTaskConflictError(
                "background task idempotency key reused with another task"
            )
        return attempt, created

    async def get(
        self,
        task_id: str,
        *,
        owner: str | None = None,
    ) -> BackgroundTaskAttempt | None:
        owner_clause = " AND owner_principal_id = %s" if owner is not None else ""
        params: tuple[object, ...] = (task_id, owner) if owner is not None else (task_id,)
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_ATTEMPT_COLUMNS} FROM background_task_attempt "
                f"WHERE task_id = %s{owner_clause}",
                params,
            )
            row = await cursor.fetchone()
        return _attempt(row) if row is not None else None

    async def list(
        self,
        *,
        owner: str | None = None,
        limit: int = 100,
    ) -> tuple[BackgroundTaskAttempt, ...]:
        _limit(limit, 1_000)
        owner_clause = "WHERE owner_principal_id = %s " if owner is not None else ""
        params: tuple[object, ...] = (owner, limit) if owner is not None else (limit,)
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_ATTEMPT_COLUMNS} FROM background_task_attempt "
                f"{owner_clause}ORDER BY updated_at DESC, task_id DESC LIMIT %s",
                params,
            )
            rows = await cursor.fetchall()
        return tuple(_attempt(row) for row in rows)

    async def claim_next(
        self,
        *,
        coordinator: str,
        lease_token: str,
        now: datetime,
        lease_seconds: int,
    ) -> BackgroundTaskAttempt | None:
        _lease_input(coordinator, lease_token, now, lease_seconds)
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "WITH candidate AS ("
                "SELECT attempt_id FROM background_task_attempt "
                "WHERE status = %s ORDER BY created_at, attempt_id "
                "FOR UPDATE SKIP LOCKED LIMIT 1"
                ") UPDATE background_task_attempt AS attempt SET "
                "status = %s, revision = attempt.revision + 1, updated_at = %s, "
                "lease_owner = %s, lease_token = %s, lease_expires_at = %s "
                "FROM candidate WHERE attempt.attempt_id = candidate.attempt_id "
                f"RETURNING {_qualified_attempt_columns('attempt')}",
                (
                    BackgroundTaskStatus.QUEUED.value,
                    BackgroundTaskStatus.CLAIMED.value,
                    now,
                    coordinator,
                    lease_token,
                    lease_expires_at,
                ),
            )
            row = await cursor.fetchone()
        return _attempt(row) if row is not None else None

    async def start(
        self,
        attempt_id: str,
        *,
        expected_revision: int,
        lease_token: str,
        now: datetime,
    ) -> BackgroundTaskAttempt:
        row = await self._leased_update(
            "UPDATE background_task_attempt SET status = %s, revision = revision + 1, "
            "updated_at = %s WHERE attempt_id = %s AND revision = %s "
            "AND lease_token = %s AND lease_expires_at > %s AND status = ANY(%s) "
            f"RETURNING {_ATTEMPT_COLUMNS}",
            (
                BackgroundTaskStatus.RUNNING.value,
                now,
                attempt_id,
                expected_revision,
                lease_token,
                now,
                [BackgroundTaskStatus.CLAIMED.value],
            ),
            attempt_id,
        )
        return _attempt(row)

    async def renew(
        self,
        attempt_id: str,
        *,
        expected_revision: int,
        lease_token: str,
        now: datetime,
        lease_seconds: int,
        usage: BackgroundTaskUsage,
    ) -> BackgroundTaskAttempt:
        _lease_input("coordinator", lease_token, now, lease_seconds)
        row = await self._leased_update(
            "UPDATE background_task_attempt SET revision = revision + 1, "
            "updated_at = %s, lease_expires_at = %s, usage = %s::jsonb "
            "WHERE attempt_id = %s AND revision = %s AND lease_token = %s "
            "AND lease_expires_at > %s AND status = ANY(%s) "
            f"RETURNING {_ATTEMPT_COLUMNS}",
            (
                now,
                now + timedelta(seconds=lease_seconds),
                json.dumps(_usage_to_dict(usage)),
                attempt_id,
                expected_revision,
                lease_token,
                now,
                [
                    BackgroundTaskStatus.CLAIMED.value,
                    BackgroundTaskStatus.RUNNING.value,
                ],
            ),
            attempt_id,
        )
        return _attempt(row)

    async def complete(
        self,
        attempt_id: str,
        *,
        expected_revision: int,
        lease_token: str,
        status: BackgroundTaskStatus,
        result: BackgroundTaskResult,
        now: datetime,
    ) -> BackgroundTaskAttempt:
        if status not in TERMINAL_BACKGROUND_STATUSES:
            raise ValueError("completion status MUST be terminal")
        row = await self._leased_update(
            "UPDATE background_task_attempt SET status = %s, revision = revision + 1, "
            "updated_at = %s, lease_owner = NULL, lease_token = NULL, "
            "lease_expires_at = NULL, usage = %s::jsonb, result = %s::jsonb "
            "WHERE attempt_id = %s AND revision = %s AND lease_token = %s "
            "AND lease_expires_at > %s AND status = ANY(%s) "
            f"RETURNING {_ATTEMPT_COLUMNS}",
            (
                status.value,
                now,
                json.dumps(_usage_to_dict(result.usage)),
                json.dumps(_result_to_dict(result)),
                attempt_id,
                expected_revision,
                lease_token,
                now,
                [
                    BackgroundTaskStatus.CLAIMED.value,
                    BackgroundTaskStatus.RUNNING.value,
                ],
            ),
            attempt_id,
        )
        return _attempt(row)

    async def cancel(
        self,
        task_id: str,
        *,
        actor: str,
        is_admin: bool,
        now: datetime,
    ) -> BackgroundTaskAttempt:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_ATTEMPT_COLUMNS} FROM background_task_attempt "
                "WHERE task_id = %s FOR UPDATE",
                (task_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                raise LookupError(f"background task {task_id!r} was not found")
            current = _attempt(row)
            if actor != current.task.owner_principal_id and not is_admin:
                raise PermissionError("background task cancellation owner mismatch")
            if current.status in TERMINAL_BACKGROUND_STATUSES:
                return current
            started_at = max(current.task.created_at, current.updated_at)
            result = BackgroundTaskResult(
                summary=None,
                evidence_refs=(),
                terminal_reason="cancelled_by_operator",
                usage=current.usage,
                started_at=started_at,
                finished_at=max(now, started_at),
            )
            updated_at = max(now, current.updated_at)
            updated = await connection.execute(
                "UPDATE background_task_attempt SET status = %s, "
                "revision = revision + 1, updated_at = %s, lease_owner = NULL, "
                "lease_token = NULL, lease_expires_at = NULL, result = %s::jsonb "
                "WHERE attempt_id = %s AND revision = %s "
                f"RETURNING {_ATTEMPT_COLUMNS}",
                (
                    BackgroundTaskStatus.CANCELLED.value,
                    updated_at,
                    json.dumps(_result_to_dict(result)),
                    current.attempt_id,
                    current.revision,
                ),
            )
            updated_row = await updated.fetchone()
        if updated_row is None:  # pragma: no cover - row lock prevents this path
            raise BackgroundTaskConflictError("background task cancellation conflict")
        return _attempt(updated_row)

    async def append_progress(
        self,
        progress: BackgroundTaskProgress,
    ) -> BackgroundTaskProgress:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            locked = await connection.execute(
                "SELECT max_progress_events FROM background_task_attempt "
                "WHERE attempt_id = %s FOR UPDATE",
                (progress.attempt_id,),
            )
            attempt_row = await locked.fetchone()
            if attempt_row is None:
                raise LookupError(f"background task attempt {progress.attempt_id!r} was not found")
            count_cursor = await connection.execute(
                "SELECT COUNT(*) AS event_count FROM background_task_progress "
                "WHERE attempt_id = %s",
                (progress.attempt_id,),
            )
            count_row = await count_cursor.fetchone()
            if count_row is None:  # pragma: no cover - aggregate always returns one row
                raise RuntimeError("background task progress count returned no row")
            event_count = int(count_row["event_count"])
            if event_count >= int(attempt_row["max_progress_events"]):
                raise BackgroundTaskConflictError("background task progress cap reached")
            if progress.sequence != event_count:
                raise BackgroundTaskConflictError("background task progress sequence conflict")
            cursor = await connection.execute(
                "INSERT INTO background_task_progress ("
                f"{_PROGRESS_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s::jsonb) "
                f"RETURNING {_PROGRESS_COLUMNS}",
                (
                    progress.attempt_id,
                    progress.sequence,
                    progress.kind,
                    progress.message,
                    progress.at,
                    json.dumps(_usage_to_dict(progress.usage)),
                ),
            )
            row = await cursor.fetchone()
        if row is None:  # pragma: no cover - INSERT RETURNING always returns one row
            raise RuntimeError("background task progress insert returned no row")
        return _progress(row)

    async def progress(
        self,
        task_id: str,
        *,
        owner: str | None = None,
        limit: int = 100,
    ) -> tuple[BackgroundTaskProgress, ...]:
        _limit(limit, 1_000)
        owner_clause = " AND owner_principal_id = %s" if owner is not None else ""
        owner_params: tuple[object, ...] = (task_id, owner) if owner is not None else (task_id,)
        async with await self._connect() as connection:
            await self._timeout(connection)
            attempt_cursor = await connection.execute(
                f"SELECT attempt_id FROM background_task_attempt WHERE task_id = %s{owner_clause}",
                owner_params,
            )
            attempt_row = await attempt_cursor.fetchone()
            if attempt_row is None:
                raise LookupError(f"background task {task_id!r} was not found")
            cursor = await connection.execute(
                f"SELECT {_PROGRESS_COLUMNS} FROM background_task_progress "
                "WHERE attempt_id = %s ORDER BY sequence DESC LIMIT %s",
                (str(attempt_row["attempt_id"]), limit),
            )
            rows = list(await cursor.fetchall())
        rows.reverse()
        return tuple(_progress(row) for row in rows)

    async def reconcile_expired(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> tuple[BackgroundTaskAttempt, ...]:
        _limit(limit, 1_000)
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            candidates = await connection.execute(
                "SELECT attempt_id FROM background_task_attempt "
                "WHERE status = ANY(%s) AND lease_expires_at <= %s "
                "ORDER BY lease_expires_at, attempt_id FOR UPDATE SKIP LOCKED LIMIT %s",
                (
                    [
                        BackgroundTaskStatus.CLAIMED.value,
                        BackgroundTaskStatus.RUNNING.value,
                    ],
                    now,
                    limit,
                ),
            )
            candidate_rows = await candidates.fetchall()
            reconciled: list[BackgroundTaskAttempt] = []
            for candidate in candidate_rows:
                attempt_cursor = await connection.execute(
                    f"SELECT {_ATTEMPT_COLUMNS} FROM background_task_attempt WHERE attempt_id = %s",
                    (str(candidate["attempt_id"]),),
                )
                row = await attempt_cursor.fetchone()
                if row is None:  # pragma: no cover - row lock keeps it present
                    continue
                current = _attempt(row)
                started_at = max(current.task.created_at, current.updated_at)
                result = BackgroundTaskResult(
                    summary=None,
                    evidence_refs=(),
                    terminal_reason="process_lost",
                    usage=current.usage,
                    started_at=started_at,
                    finished_at=max(now, started_at),
                )
                updated = await connection.execute(
                    "UPDATE background_task_attempt SET status = %s, "
                    "revision = revision + 1, updated_at = %s, lease_owner = NULL, "
                    "lease_token = NULL, lease_expires_at = NULL, result = %s::jsonb "
                    "WHERE attempt_id = %s AND revision = %s "
                    f"RETURNING {_ATTEMPT_COLUMNS}",
                    (
                        BackgroundTaskStatus.UNKNOWN.value,
                        max(now, current.updated_at),
                        json.dumps(_result_to_dict(result)),
                        current.attempt_id,
                        current.revision,
                    ),
                )
                updated_row = await updated.fetchone()
                if updated_row is not None:
                    reconciled.append(_attempt(updated_row))
        return tuple(reconciled)

    async def _leased_update(
        self,
        query: str,
        params: tuple[object, ...],
        attempt_id: str,
    ) -> dict[str, Any]:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(query, params)
            row = await cursor.fetchone()
        if row is not None:
            return row
        if await self._attempt_exists(attempt_id):
            raise BackgroundTaskConflictError("background task lease or revision conflict")
        raise LookupError(f"background task attempt {attempt_id!r} was not found")

    async def _attempt_exists(self, attempt_id: str) -> bool:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT 1 FROM background_task_attempt WHERE attempt_id = %s",
                (attempt_id,),
            )
            return await cursor.fetchone() is not None

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


def _attempt(row: dict[str, Any]) -> BackgroundTaskAttempt:
    lease_owner = row["lease_owner"]
    result_raw = row["result"]
    return BackgroundTaskAttempt(
        attempt_id=str(row["attempt_id"]),
        task=_task(_mapping(row["task"])),
        attempt_number=int(row["attempt_number"]),
        status=BackgroundTaskStatus(str(row["status"])),
        revision=int(row["revision"]),
        updated_at=row["updated_at"],
        lease=(
            BackgroundTaskLease(
                owner=str(lease_owner),
                token=str(row["lease_token"]),
                expires_at=row["lease_expires_at"],
            )
            if lease_owner is not None
            else None
        ),
        usage=_usage(_mapping(row["usage"])),
        result=_result(_mapping(result_raw)) if result_raw is not None else None,
        parent_attempt_id=(
            str(row["parent_attempt_id"]) if row["parent_attempt_id"] is not None else None
        ),
    )


def _progress(row: dict[str, Any]) -> BackgroundTaskProgress:
    return BackgroundTaskProgress(
        attempt_id=str(row["attempt_id"]),
        sequence=int(row["sequence"]),
        kind=str(row["kind"]),
        message=str(row["message"]),
        at=row["at"],
        usage=_usage(_mapping(row["usage"])),
    )


def _task_to_dict(task: BackgroundTask) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "owner_principal_id": task.owner_principal_id,
        "origin": {
            "conversation_id": task.origin.conversation_id,
            "channel_kind": task.origin.channel_kind,
            "channel_id": task.origin.channel_id,
            "thread_id": task.origin.thread_id,
        },
        "kind": task.kind.value,
        "prompt": task.prompt,
        "context_digest": task.context_digest,
        "capability_profile_id": task.capability_profile_id,
        "budget": {
            "max_wall_seconds": task.budget.max_wall_seconds,
            "max_tokens": task.budget.max_tokens,
            "max_cost_microusd": task.budget.max_cost_microusd,
            "max_tool_calls": task.budget.max_tool_calls,
            "max_progress_events": task.budget.max_progress_events,
        },
        "correlation_id": task.correlation_id,
        "idempotency_key": task.idempotency_key,
        "created_at": task.created_at.isoformat(),
        "retention_until": task.retention_until.isoformat(),
        "retryable": task.retryable,
    }


def _task(raw: dict[str, Any]) -> BackgroundTask:
    origin = _mapping(raw["origin"])
    budget = _mapping(raw["budget"])
    thread_id = origin.get("thread_id")
    return BackgroundTask(
        task_id=str(raw["task_id"]),
        owner_principal_id=str(raw["owner_principal_id"]),
        origin=BackgroundTaskOrigin(
            conversation_id=str(origin["conversation_id"]),
            channel_kind=str(origin["channel_kind"]),
            channel_id=str(origin["channel_id"]),
            thread_id=str(thread_id) if thread_id is not None else None,
        ),
        kind=BackgroundTaskKind(str(raw["kind"])),
        prompt=str(raw["prompt"]),
        context_digest=str(raw["context_digest"]),
        capability_profile_id=str(raw["capability_profile_id"]),
        budget=BackgroundTaskBudget(
            max_wall_seconds=int(budget["max_wall_seconds"]),
            max_tokens=int(budget["max_tokens"]),
            max_cost_microusd=int(budget["max_cost_microusd"]),
            max_tool_calls=int(budget["max_tool_calls"]),
            max_progress_events=int(budget["max_progress_events"]),
        ),
        correlation_id=str(raw["correlation_id"]),
        idempotency_key=str(raw["idempotency_key"]),
        created_at=datetime.fromisoformat(str(raw["created_at"])),
        retention_until=datetime.fromisoformat(str(raw["retention_until"])),
        retryable=bool(raw["retryable"]),
    )


def _usage_to_dict(usage: BackgroundTaskUsage) -> dict[str, int]:
    return {
        "tokens": usage.tokens,
        "cost_microusd": usage.cost_microusd,
        "tool_calls": usage.tool_calls,
    }


def _usage(raw: dict[str, Any]) -> BackgroundTaskUsage:
    return BackgroundTaskUsage(
        tokens=int(raw["tokens"]),
        cost_microusd=int(raw["cost_microusd"]),
        tool_calls=int(raw["tool_calls"]),
    )


def _result_to_dict(result: BackgroundTaskResult) -> dict[str, Any]:
    return {
        "summary": result.summary,
        "evidence_refs": list(result.evidence_refs),
        "terminal_reason": result.terminal_reason,
        "usage": _usage_to_dict(result.usage),
        "started_at": result.started_at.isoformat(),
        "finished_at": result.finished_at.isoformat(),
        "trusted": result.trusted,
    }


def _result(raw: dict[str, Any]) -> BackgroundTaskResult:
    summary = raw.get("summary")
    return BackgroundTaskResult(
        summary=str(summary) if summary is not None else None,
        evidence_refs=tuple(str(item) for item in raw["evidence_refs"]),
        terminal_reason=str(raw["terminal_reason"]),
        usage=_usage(_mapping(raw["usage"])),
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
    raise RuntimeError("background task JSON column is not an object")


def _qualified_attempt_columns(alias: str) -> str:
    return ", ".join(f"{alias}.{column.strip()}" for column in _ATTEMPT_COLUMNS.split(","))


def _lease_input(coordinator: str, lease_token: str, now: datetime, lease_seconds: int) -> None:
    if not coordinator or not lease_token or now.tzinfo is None or not 1 <= lease_seconds <= 300:
        raise ValueError("background task lease input is invalid")


def _limit(value: int, maximum: int) -> None:
    if not 1 <= value <= maximum:
        raise ValueError(f"limit MUST be in [1, {maximum}]")


__all__ = ["PostgresBackgroundTaskStore", "PostgresBackgroundTaskStoreConfig"]
