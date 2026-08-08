"""PostgreSQL store for durable detached background task attempts."""

# ruff: noqa: S608 - interpolated identifiers are module constants; values are bound.

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn

import psycopg
from psycopg.rows import dict_row

from fdai.core.background_task import (
    TERMINAL_BACKGROUND_STATUSES,
    BackgroundTask,
    BackgroundTaskAttempt,
    BackgroundTaskCompletion,
    BackgroundTaskConflictError,
    BackgroundTaskProgress,
    BackgroundTaskQuotaPolicy,
    BackgroundTaskQuotaUsage,
    BackgroundTaskResult,
    BackgroundTaskStatus,
    BackgroundTaskUsage,
    background_task_quota_time,
    enforce_background_task_quota,
)
from fdai.delivery.persistence.postgres_background_task_completion import (
    PostgresBackgroundTaskCompletionDelivery,
)
from fdai.delivery.persistence.postgres_background_task_serialization import (
    ATTEMPT_COLUMNS as _ATTEMPT_COLUMNS,
)
from fdai.delivery.persistence.postgres_background_task_serialization import (
    PROGRESS_COLUMNS as _PROGRESS_COLUMNS,
)
from fdai.delivery.persistence.postgres_background_task_serialization import (
    attempt_from_row as _attempt,
)
from fdai.delivery.persistence.postgres_background_task_serialization import (
    progress_from_row as _progress,
)
from fdai.delivery.persistence.postgres_background_task_serialization import (
    qualified_attempt_columns as _qualified_attempt_columns,
)
from fdai.delivery.persistence.postgres_background_task_serialization import (
    result_to_dict as _result_to_dict,
)
from fdai.delivery.persistence.postgres_background_task_serialization import (
    task_to_dict as _task_to_dict,
)
from fdai.delivery.persistence.postgres_background_task_serialization import (
    usage_to_dict as _usage_to_dict,
)


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
    def __init__(
        self,
        *,
        config: PostgresBackgroundTaskStoreConfig,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._clock = clock or (lambda: datetime.now(UTC))
        self._completion_delivery = PostgresBackgroundTaskCompletionDelivery(
            connect=self._connect,
            set_timeout=self._timeout,
        )

    async def create(
        self,
        task: BackgroundTask,
        *,
        quota: BackgroundTaskQuotaPolicy | None = None,
    ) -> tuple[BackgroundTaskAttempt, bool]:
        attempt_id = f"{task.task_id}:1"
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            if quota is not None:
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (task.owner_principal_id,),
                )
            existing = await connection.execute(
                f"SELECT {_ATTEMPT_COLUMNS} FROM background_task_attempt "
                "WHERE task_id = %s OR "
                "(owner_principal_id = %s AND idempotency_key = %s) "
                "FOR UPDATE",
                (task.task_id, task.owner_principal_id, task.idempotency_key),
            )
            rows = await existing.fetchall()
            if len(rows) > 1:
                raise BackgroundTaskConflictError("background task id or idempotency key conflict")
            if rows:
                row = rows[0]
                created = False
            else:
                if quota is not None:
                    quota_now = background_task_quota_time(task, now=self._clock())
                    day_start = quota_now.astimezone(UTC).replace(
                        hour=0,
                        minute=0,
                        second=0,
                        microsecond=0,
                    )
                    active = [
                        BackgroundTaskStatus.QUEUED.value,
                        BackgroundTaskStatus.CLAIMED.value,
                        BackgroundTaskStatus.RUNNING.value,
                    ]
                    quota_cursor = await connection.execute(
                        "SELECT "
                        "COUNT(*) FILTER (WHERE status = ANY(%s)) AS active_tasks, "
                        "COALESCE(SUM(CASE WHEN status = ANY(%s) THEN "
                        "COALESCE((task->'budget'->>'max_cost_microusd')::bigint, 0) "
                        "ELSE COALESCE((usage->>'cost_microusd')::bigint, 0) END), 0) "
                        "AS daily_cost_microusd "
                        "FROM background_task_attempt "
                        "WHERE owner_principal_id = %s AND created_at >= %s "
                        "AND created_at < %s",
                        (
                            active,
                            active,
                            task.owner_principal_id,
                            day_start,
                            day_start + timedelta(days=1),
                        ),
                    )
                    quota_row = await quota_cursor.fetchone()
                    if quota_row is None:
                        raise RuntimeError("background task quota aggregate returned no row")
                    enforce_background_task_quota(
                        policy=quota,
                        budget=task.budget,
                        usage=BackgroundTaskQuotaUsage(
                            active_tasks=int(quota_row["active_tasks"]),
                            daily_cost_microusd=int(quota_row["daily_cost_microusd"]),
                        ),
                    )
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
                inserted_row = await cursor.fetchone()
                if inserted_row is None:
                    raise BackgroundTaskConflictError(
                        "background task id or idempotency key conflict"
                    )
                row = inserted_row
                created = True
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
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
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
            )
            row = await cursor.fetchone()
            if row is None:
                await self._raise_attempt_conflict(connection, attempt_id)
            completed = _attempt(row)
            await self._insert_completion(connection, completed, now=now)
            return completed

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
            completed = _attempt(updated_row)
            await self._insert_completion(connection, completed, now=updated_at)
            return completed

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
                    completed = _attempt(updated_row)
                    await self._insert_completion(
                        connection,
                        completed,
                        now=completed.updated_at,
                    )
                    reconciled.append(completed)
        return tuple(reconciled)

    async def claim_completion(
        self,
        *,
        coordinator: str,
        lease_token: str,
        now: datetime,
        lease_seconds: int,
    ) -> tuple[BackgroundTaskCompletion, BackgroundTaskAttempt] | None:
        return await self._completion_delivery.claim(
            coordinator=coordinator,
            lease_token=lease_token,
            now=now,
            lease_seconds=lease_seconds,
        )

    async def finish_completion(
        self,
        attempt_id: str,
        *,
        lease_token: str,
        delivered: bool,
        now: datetime,
        retry_at: datetime | None = None,
        error_code: str | None = None,
    ) -> BackgroundTaskCompletion:
        return await self._completion_delivery.finish(
            attempt_id,
            lease_token=lease_token,
            delivered=delivered,
            now=now,
            retry_at=retry_at,
            error_code=error_code,
        )

    async def reconcile_completion_expired(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> tuple[BackgroundTaskCompletion, ...]:
        return await self._completion_delivery.reconcile_expired(now=now, limit=limit)

    async def purge_retained(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> tuple[str, ...]:
        return await self._completion_delivery.purge_retained(now=now, limit=limit)

    async def _insert_completion(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        attempt: BackgroundTaskAttempt,
        *,
        now: datetime,
    ) -> None:
        await self._completion_delivery.insert(connection, attempt, now=now)

    async def _raise_attempt_conflict(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        attempt_id: str,
    ) -> NoReturn:
        cursor = await connection.execute(
            "SELECT 1 FROM background_task_attempt WHERE attempt_id = %s",
            (attempt_id,),
        )
        if await cursor.fetchone() is not None:
            raise BackgroundTaskConflictError("background task lease or revision conflict")
        raise LookupError(f"background task attempt {attempt_id!r} was not found")

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


def _lease_input(coordinator: str, lease_token: str, now: datetime, lease_seconds: int) -> None:
    if not coordinator or not lease_token or now.tzinfo is None or not 1 <= lease_seconds <= 300:
        raise ValueError("background task lease input is invalid")


def _limit(value: int, maximum: int) -> None:
    if not 1 <= value <= maximum:
        raise ValueError(f"limit MUST be in [1, {maximum}]")


__all__ = ["PostgresBackgroundTaskStore", "PostgresBackgroundTaskStoreConfig"]
