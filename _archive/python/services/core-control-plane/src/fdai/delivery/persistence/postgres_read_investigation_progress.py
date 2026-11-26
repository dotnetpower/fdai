"""PostgreSQL append-only progress for interactive read investigations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.core.read_investigation.interactive import ReadInvestigationRunProgress
from fdai.core.read_investigation.progress import ReadInvestigationProgressKind


@dataclass(frozen=True, slots=True)
class PostgresReadInvestigationProgressStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("progress store dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("progress store timeouts MUST be positive")


class PostgresReadInvestigationProgressStore:
    """Append monotonic progress after verifying the Core-owned run identity."""

    def __init__(self, *, config: PostgresReadInvestigationProgressStoreConfig) -> None:
        self._config = config

    async def verify_schema(self) -> None:
        """Fail startup when the progress migration is unavailable."""

        async with await self._connect() as connection:
            await self._timeout(connection)
            await connection.execute("SELECT 1 FROM read_investigation_run_progress LIMIT 0")

    async def append(
        self,
        *,
        task_id: str,
        owner_principal_id: str,
        kind: ReadInvestigationProgressKind,
        recorded_at: datetime,
        limit: int,
    ) -> ReadInvestigationRunProgress:
        _aware(recorded_at)
        _limit(limit)
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            run_cursor = await connection.execute(
                "SELECT owner_principal_id, state FROM read_investigation_run "
                "WHERE task_id = %s FOR UPDATE",
                (task_id,),
            )
            run = await run_cursor.fetchone()
            if run is None:
                raise LookupError("read investigation run was not found")
            if str(run["owner_principal_id"]) != owner_principal_id:
                raise PermissionError("read investigation progress owner mismatch")
            if str(run["state"]) != "running":
                raise RuntimeError("read investigation progress requires a running run")
            latest_cursor = await connection.execute(
                "SELECT task_id, owner_principal_id, sequence, kind, recorded_at "
                "FROM read_investigation_run_progress WHERE task_id = %s "
                "ORDER BY sequence DESC LIMIT 1",
                (task_id,),
            )
            latest = await latest_cursor.fetchone()
            if latest is not None and int(latest["sequence"]) >= limit:
                return _progress(latest)
            sequence = 1 if latest is None else int(latest["sequence"]) + 1
            inserted = await connection.execute(
                "INSERT INTO read_investigation_run_progress ("
                "task_id, owner_principal_id, sequence, kind, recorded_at"
                ") VALUES (%s, %s, %s, %s, %s) RETURNING "
                "task_id, owner_principal_id, sequence, kind, recorded_at",
                (task_id, owner_principal_id, sequence, kind.value, recorded_at),
            )
            row = await inserted.fetchone()
            if row is None:  # pragma: no cover - INSERT RETURNING contract
                raise RuntimeError("read investigation progress insert returned no row")
            return _progress(row)

    async def list_after(
        self,
        *,
        task_id: str,
        owner_principal_id: str,
        after_sequence: int,
        limit: int,
    ) -> tuple[ReadInvestigationRunProgress, ...]:
        if after_sequence < 0:
            raise ValueError("after_sequence MUST be non-negative")
        _limit(limit)
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT progress.task_id, progress.owner_principal_id, progress.sequence, "
                "progress.kind, progress.recorded_at "
                "FROM read_investigation_run_progress AS progress "
                "JOIN read_investigation_run AS run ON run.task_id = progress.task_id "
                "WHERE progress.task_id = %s AND run.owner_principal_id = %s "
                "AND progress.sequence > %s ORDER BY progress.sequence LIMIT %s",
                (task_id, owner_principal_id, after_sequence, limit),
            )
            rows = await cursor.fetchall()
        return tuple(_progress(row) for row in rows)

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


def _progress(row: dict[str, Any]) -> ReadInvestigationRunProgress:
    return ReadInvestigationRunProgress(
        task_id=str(row["task_id"]),
        owner_principal_id=str(row["owner_principal_id"]),
        sequence=int(row["sequence"]),
        kind=ReadInvestigationProgressKind(str(row["kind"])),
        recorded_at=row["recorded_at"],
    )


def _limit(value: int) -> None:
    if not 1 <= value <= 256:
        raise ValueError("progress limit MUST be in [1, 256]")


def _aware(value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError("progress recorded_at MUST be timezone-aware")


__all__ = [
    "PostgresReadInvestigationProgressStore",
    "PostgresReadInvestigationProgressStoreConfig",
]
