"""Completion outbox delivery for PostgreSQL background tasks."""

# ruff: noqa: S608 - interpolated identifiers are module constants; values are bound.

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

import psycopg

from fdai.core.background_task import (
    MAX_COMPLETION_ATTEMPTS,
    TERMINAL_BACKGROUND_STATUSES,
    BackgroundTaskAttempt,
    BackgroundTaskCompletion,
    BackgroundTaskCompletionState,
    BackgroundTaskConflictError,
)
from fdai.delivery.persistence.postgres_background_task_serialization import (
    ATTEMPT_COLUMNS,
    COMPLETION_COLUMNS,
    attempt_from_row,
    completion_from_row,
    qualified_completion_columns,
)

Connection = psycopg.AsyncConnection[dict[str, Any]]
Connect = Callable[[], Awaitable[Connection]]
SetTimeout = Callable[[psycopg.AsyncConnection[Any]], Awaitable[None]]


class PostgresBackgroundTaskCompletionDelivery:
    def __init__(self, *, connect: Connect, set_timeout: SetTimeout) -> None:
        self._connect = connect
        self._set_timeout = set_timeout

    async def claim(
        self,
        *,
        coordinator: str,
        lease_token: str,
        now: datetime,
        lease_seconds: int,
    ) -> tuple[BackgroundTaskCompletion, BackgroundTaskAttempt] | None:
        _lease_input(coordinator, lease_token, now, lease_seconds)
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                "WITH candidate AS ("
                "SELECT attempt_id FROM background_task_completion "
                "WHERE state = ANY(%s) AND due_at <= %s AND attempt_count < %s "
                "ORDER BY due_at, attempt_id FOR UPDATE SKIP LOCKED LIMIT 1"
                ") UPDATE background_task_completion AS completion SET "
                "state = %s, attempt_count = completion.attempt_count + 1, "
                "lease_owner = %s, lease_token = %s, lease_expires_at = %s, "
                "last_error_code = NULL FROM candidate "
                "WHERE completion.attempt_id = candidate.attempt_id "
                f"RETURNING {qualified_completion_columns('completion')}",
                (
                    [
                        BackgroundTaskCompletionState.PENDING.value,
                        BackgroundTaskCompletionState.FAILED.value,
                    ],
                    now,
                    MAX_COMPLETION_ATTEMPTS,
                    BackgroundTaskCompletionState.SENDING.value,
                    coordinator,
                    lease_token,
                    now + timedelta(seconds=lease_seconds),
                ),
            )
            completion_row = await cursor.fetchone()
            if completion_row is None:
                return None
            attempt_cursor = await connection.execute(
                f"SELECT {ATTEMPT_COLUMNS} FROM background_task_attempt WHERE attempt_id = %s",
                (str(completion_row["attempt_id"]),),
            )
            attempt_row = await attempt_cursor.fetchone()
            if attempt_row is None:  # pragma: no cover - foreign key keeps it present
                raise RuntimeError("background completion references a missing attempt")
            return completion_from_row(completion_row), attempt_from_row(attempt_row)

    async def finish(
        self,
        attempt_id: str,
        *,
        lease_token: str,
        delivered: bool,
        now: datetime,
        retry_at: datetime | None = None,
        error_code: str | None = None,
    ) -> BackgroundTaskCompletion:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            current = await self._leased(
                connection,
                attempt_id,
                lease_token=lease_token,
                now=now,
            )
            if delivered:
                if retry_at is not None or error_code is not None:
                    raise ValueError("delivered completion cannot carry retry details")
                cursor = await connection.execute(
                    "UPDATE background_task_completion SET "
                    "state = %s, lease_owner = NULL, lease_token = NULL, "
                    "lease_expires_at = NULL, last_error_code = NULL, terminal_at = %s "
                    "WHERE attempt_id = %s RETURNING "
                    f"{COMPLETION_COLUMNS}",
                    (
                        BackgroundTaskCompletionState.DELIVERED.value,
                        now,
                        attempt_id,
                    ),
                )
            else:
                if retry_at is None or error_code is None:
                    raise ValueError("failed completion requires retry_at and error_code")
                if retry_at.tzinfo is None or retry_at.utcoffset() is None:
                    raise ValueError("completion retry_at MUST be timezone-aware")
                abandon = (
                    current.attempt_count >= MAX_COMPLETION_ATTEMPTS
                    or retry_at >= current.retention_until
                )
                cursor = await connection.execute(
                    "UPDATE background_task_completion SET "
                    "state = %s, due_at = %s, lease_owner = NULL, lease_token = NULL, "
                    "lease_expires_at = NULL, last_error_code = %s, terminal_at = %s "
                    "WHERE attempt_id = %s RETURNING "
                    f"{COMPLETION_COLUMNS}",
                    (
                        (
                            BackgroundTaskCompletionState.ABANDONED.value
                            if abandon
                            else BackgroundTaskCompletionState.FAILED.value
                        ),
                        min(retry_at, current.retention_until),
                        error_code,
                        now if abandon else None,
                        attempt_id,
                    ),
                )
            row = await cursor.fetchone()
            if row is None:  # pragma: no cover - UPDATE RETURNING yields one row
                raise RuntimeError("background completion update returned no row")
            return completion_from_row(row)

    async def reconcile_expired(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> tuple[BackgroundTaskCompletion, ...]:
        _limit(limit, 1_000)
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            candidates = await connection.execute(
                f"SELECT {COMPLETION_COLUMNS} FROM background_task_completion "
                "WHERE state = %s AND lease_expires_at <= %s "
                "ORDER BY lease_expires_at, attempt_id FOR UPDATE SKIP LOCKED LIMIT %s",
                (
                    BackgroundTaskCompletionState.SENDING.value,
                    now,
                    limit,
                ),
            )
            rows = await candidates.fetchall()
            reconciled: list[BackgroundTaskCompletion] = []
            for row in rows:
                current = completion_from_row(row)
                abandon = (
                    current.attempt_count >= MAX_COMPLETION_ATTEMPTS
                    or now >= current.retention_until
                )
                updated = await connection.execute(
                    "UPDATE background_task_completion SET "
                    "state = %s, due_at = %s, lease_owner = NULL, lease_token = NULL, "
                    "lease_expires_at = NULL, last_error_code = %s, terminal_at = %s "
                    "WHERE attempt_id = %s RETURNING "
                    f"{COMPLETION_COLUMNS}",
                    (
                        (
                            BackgroundTaskCompletionState.ABANDONED.value
                            if abandon
                            else BackgroundTaskCompletionState.FAILED.value
                        ),
                        min(now, current.retention_until),
                        "process_lost",
                        now if abandon else None,
                        current.attempt_id,
                    ),
                )
                updated_row = await updated.fetchone()
                if updated_row is None:  # pragma: no cover - row lock keeps it present
                    continue
                reconciled.append(completion_from_row(updated_row))
        return tuple(reconciled)

    async def purge_retained(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> tuple[str, ...]:
        _limit(limit, 1_000)
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                "WITH candidate AS ("
                "SELECT attempt.attempt_id, attempt.task_id "
                "FROM background_task_attempt AS attempt "
                "JOIN background_task_completion AS completion "
                "ON completion.attempt_id = attempt.attempt_id "
                "WHERE attempt.status = ANY(%s) "
                "AND attempt.retention_until <= %s "
                "AND completion.state = ANY(%s) "
                "ORDER BY attempt.retention_until, attempt.attempt_id "
                "FOR UPDATE OF attempt SKIP LOCKED LIMIT %s"
                "), deleted AS ("
                "DELETE FROM background_task_attempt AS attempt "
                "USING candidate "
                "WHERE attempt.attempt_id = candidate.attempt_id "
                "RETURNING candidate.task_id"
                ") SELECT task_id FROM deleted",
                (
                    [status.value for status in TERMINAL_BACKGROUND_STATUSES],
                    now,
                    [
                        BackgroundTaskCompletionState.DELIVERED.value,
                        BackgroundTaskCompletionState.ABANDONED.value,
                    ],
                    limit,
                ),
            )
            rows = await cursor.fetchall()
        return tuple(str(row["task_id"]) for row in rows)

    async def insert(
        self,
        connection: Connection,
        attempt: BackgroundTaskAttempt,
        *,
        now: datetime,
    ) -> None:
        if attempt.status not in TERMINAL_BACKGROUND_STATUSES:
            raise ValueError("completion outbox requires a terminal attempt")
        await connection.execute(
            "INSERT INTO background_task_completion ("
            f"{COMPLETION_COLUMNS}) VALUES ("
            "%s, %s, %s, %s, GREATEST(%s, %s), %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (attempt_id) DO NOTHING",
            (
                attempt.attempt_id,
                BackgroundTaskCompletionState.PENDING.value,
                now,
                now,
                attempt.task.retention_until,
                now,
                0,
                None,
                None,
                None,
                None,
                None,
            ),
        )

    async def _leased(
        self,
        connection: Connection,
        attempt_id: str,
        *,
        lease_token: str,
        now: datetime,
    ) -> BackgroundTaskCompletion:
        cursor = await connection.execute(
            f"SELECT {COMPLETION_COLUMNS} FROM background_task_completion "
            "WHERE attempt_id = %s FOR UPDATE",
            (attempt_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise LookupError(f"background completion {attempt_id!r} was not found")
        current = completion_from_row(row)
        if (
            current.state is not BackgroundTaskCompletionState.SENDING
            or current.lease is None
            or current.lease.token != lease_token
            or current.lease.expires_at <= now
        ):
            raise BackgroundTaskConflictError("background completion lease conflict")
        return current


def _lease_input(coordinator: str, lease_token: str, now: datetime, lease_seconds: int) -> None:
    if not coordinator or not lease_token or now.tzinfo is None or not 1 <= lease_seconds <= 300:
        raise ValueError("background task lease input is invalid")


def _limit(value: int, maximum: int) -> None:
    if not 1 <= value <= maximum:
        raise ValueError(f"limit MUST be in [1, {maximum}]")
