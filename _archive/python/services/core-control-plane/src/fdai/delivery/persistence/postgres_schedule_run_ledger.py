"""PostgreSQL implementation of the scheduler dispatch run ledger."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.core.scheduler.run_ledger import (
    ScheduleDispatchRun,
    ScheduleDispatchStatus,
)

_COLUMNS: Final = (
    "run_id, task_id, scheduled_for, claimed_at, status, attempt, completed_at, error_kind"
)


@dataclass(frozen=True, slots=True)
class PostgresScheduleRunLedgerConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresScheduleRunLedgerConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresScheduleRunLedgerConfig timeouts MUST be positive")


class PostgresScheduleRunLedger:
    """Atomic durable claim, completion, history, and stale reconciliation."""

    def __init__(self, *, config: PostgresScheduleRunLedgerConfig) -> None:
        self._config = config

    async def claim(self, run: ScheduleDispatchRun) -> bool:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"""
                INSERT INTO schedule_dispatch_run ({_COLUMNS})
                VALUES (%s, %s, %s, %s, %s, %s, NULL, NULL)
                ON CONFLICT (run_id) DO UPDATE SET
                    scheduled_for = EXCLUDED.scheduled_for,
                    claimed_at = EXCLUDED.claimed_at,
                    status = 'claimed',
                    attempt = schedule_dispatch_run.attempt + 1,
                    completed_at = NULL,
                    error_kind = NULL,
                    updated_at = now()
                WHERE schedule_dispatch_run.status IN ('failed', 'lost')
                RETURNING run_id
                """,  # noqa: S608 - _COLUMNS is a module constant
                (
                    run.run_id,
                    run.task_id,
                    run.scheduled_for,
                    run.claimed_at,
                    run.status.value,
                    run.attempt,
                ),
            )
            return await cursor.fetchone() is not None

    async def complete(
        self,
        run_id: str,
        *,
        status: ScheduleDispatchStatus,
        at: datetime,
        error_kind: str | None = None,
    ) -> ScheduleDispatchRun:
        if status not in {ScheduleDispatchStatus.PUBLISHED, ScheduleDispatchStatus.FAILED}:
            raise ValueError("schedule dispatch completion MUST be published or failed")
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"""
                UPDATE schedule_dispatch_run
                   SET status = %s, completed_at = %s, error_kind = %s, updated_at = now()
                 WHERE run_id = %s AND status = 'claimed'
                 RETURNING {_COLUMNS}
                """,  # noqa: S608 - _COLUMNS is a module constant
                (status.value, at, error_kind, run_id),
            )
            row = await cursor.fetchone()
        if row is None:
            raise ValueError("only a claimed schedule dispatch can complete")
        return _row_to_run(row)

    async def list_for_task(self, task_id: str) -> Sequence[ScheduleDispatchRun]:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM schedule_dispatch_run "  # noqa: S608
                "WHERE task_id = %s ORDER BY scheduled_for, attempt",
                (task_id,),
            )
            rows = await cursor.fetchall()
        return tuple(_row_to_run(row) for row in rows)

    async def reconcile_stale(
        self,
        *,
        before: datetime,
        at: datetime,
    ) -> Sequence[ScheduleDispatchRun]:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"""
                UPDATE schedule_dispatch_run
                   SET status = 'lost', completed_at = %s,
                       error_kind = 'claim_expired', updated_at = now()
                 WHERE status = 'claimed' AND claimed_at <= %s
                 RETURNING {_COLUMNS}
                """,  # noqa: S608 - _COLUMNS is a module constant
                (at, before),
            )
            rows = await cursor.fetchall()
        return tuple(sorted((_row_to_run(row) for row in rows), key=lambda run: run.run_id))

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _set_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        timeout = int(self._config.statement_timeout_ms)
        await connection.execute(f"SET LOCAL statement_timeout = {timeout}")


def _row_to_run(row: dict[str, Any]) -> ScheduleDispatchRun:
    return ScheduleDispatchRun(
        run_id=str(row["run_id"]),
        task_id=str(row["task_id"]),
        scheduled_for=row["scheduled_for"],
        claimed_at=row["claimed_at"],
        status=ScheduleDispatchStatus(str(row["status"])),
        attempt=int(row["attempt"]),
        completed_at=row["completed_at"],
        error_kind=str(row["error_kind"]) if row["error_kind"] is not None else None,
    )


__all__ = ["PostgresScheduleRunLedger", "PostgresScheduleRunLedgerConfig"]
