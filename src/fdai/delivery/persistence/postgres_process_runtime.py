"""Transactional PostgreSQL Process snapshot and transition journal store."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.shared.providers.process_projection import ProcessProjectionJob
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessRevisionConflictError,
    ProcessRuntimeError,
    ProcessSnapshot,
    ProcessStatus,
)


@dataclass(frozen=True, slots=True)
class PostgresProcessRuntimeStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresProcessRuntimeStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        if self.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")


class PostgresProcessRuntimeStore:
    def __init__(self, *, config: PostgresProcessRuntimeStoreConfig) -> None:
        self._config = config

    async def create(
        self,
        *,
        snapshot: ProcessSnapshot,
        event: ProcessEvent,
    ) -> tuple[ProcessSnapshot, bool]:
        if snapshot.process_id != event.process_id:
            raise ProcessRuntimeError("snapshot and event process ids MUST match")
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                cursor = await connection.execute(
                    "INSERT INTO process_runtime "
                    "(process_id, workflow_ref, workflow_version, status, current_step, "
                    "target_resource_id, started_at, updated_at, correlation_id, revision) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1) "
                    "ON CONFLICT (process_id) DO NOTHING RETURNING *",
                    (
                        snapshot.process_id,
                        snapshot.workflow_ref,
                        snapshot.workflow_version,
                        snapshot.status.value,
                        snapshot.current_step,
                        snapshot.target_resource_id,
                        snapshot.started_at,
                        snapshot.updated_at,
                        snapshot.correlation_id,
                    ),
                )
                inserted = await cursor.fetchone()
                if inserted is None:
                    existing = await self._get_with_connection(connection, snapshot.process_id)
                    if existing is None:  # pragma: no cover - transaction invariant
                        raise ProcessRuntimeError("process insert conflict without existing row")
                    return existing, False
                await self._insert_event(connection, event)
                return _snapshot_from_row(inserted), True

    async def transition(
        self,
        *,
        process_id: str,
        expected_revision: int,
        status: ProcessStatus,
        current_step: str,
        event: ProcessEvent,
    ) -> ProcessSnapshot:
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                duplicate = await self._event_by_key(connection, event.idempotency_key)
                if duplicate is not None:
                    if duplicate.process_id != process_id:
                        raise ProcessRuntimeError(
                            "process event idempotency key belongs to another process"
                        )
                    existing = await self._get_with_connection(connection, process_id)
                    if existing is None:  # pragma: no cover - FK invariant
                        raise ProcessRuntimeError("duplicate event references missing process")
                    return existing
                cursor = await connection.execute(
                    "SELECT * FROM process_runtime WHERE process_id = %s FOR UPDATE",
                    (process_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise ProcessRuntimeError(f"unknown process {process_id!r}")
                current = _snapshot_from_row(row)
                if current.revision != expected_revision:
                    raise ProcessRevisionConflictError(
                        f"process {process_id!r} revision mismatch: "
                        f"expected {expected_revision}, current {current.revision}"
                    )
                if event.process_id != process_id:
                    raise ProcessRuntimeError("transition event process id MUST match")
                revision = current.revision + 1
                update = await connection.execute(
                    "UPDATE process_runtime SET status = %s, current_step = %s, "
                    "updated_at = %s, revision = %s WHERE process_id = %s RETURNING *",
                    (status.value, current_step, event.recorded_at, revision, process_id),
                )
                updated = await update.fetchone()
                if updated is None:  # pragma: no cover - row locked above
                    raise ProcessRuntimeError("process transition update returned no row")
                await self._insert_event(connection, event)
                return _snapshot_from_row(updated)

    async def get(self, process_id: str) -> ProcessSnapshot | None:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            return await self._get_with_connection(connection, process_id)

    async def events(self, process_id: str) -> tuple[ProcessEvent, ...]:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                "SELECT * FROM process_event WHERE process_id = %s ORDER BY seq",
                (process_id,),
            )
            return tuple(_event_from_row(row) for row in await cursor.fetchall())

    async def append_event(self, event: ProcessEvent) -> bool:
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                duplicate = await self._event_by_key(connection, event.idempotency_key)
                if duplicate is not None:
                    if duplicate.process_id != event.process_id:
                        raise ProcessRuntimeError(
                            "process event idempotency key belongs to another process"
                        )
                    return False
                cursor = await connection.execute(
                    "SELECT 1 FROM process_runtime WHERE process_id = %s",
                    (event.process_id,),
                )
                if await cursor.fetchone() is None:
                    raise ProcessRuntimeError(f"unknown process {event.process_id!r}")
                await self._insert_event(connection, event)
                return True

    async def claim_projections(
        self,
        *,
        now: datetime,
        limit: int = 100,
        lease_seconds: int = 30,
    ) -> tuple[ProcessProjectionJob, ...]:
        if now.tzinfo is None:
            raise ValueError("now MUST be timezone-aware")
        if not 1 <= limit <= 1000:
            raise ValueError("limit MUST be in [1, 1000]")
        if lease_seconds < 1:
            raise ValueError("lease_seconds MUST be >= 1")
        leased_until = now + timedelta(seconds=lease_seconds)
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                cursor = await connection.execute(
                    "SELECT event_id FROM process_projection_outbox "
                    "WHERE available_at <= %s "
                    "AND (leased_until IS NULL OR leased_until <= %s) "
                    "ORDER BY available_at, event_id "
                    "FOR UPDATE SKIP LOCKED LIMIT %s",
                    (now, now, limit),
                )
                event_ids = [str(row["event_id"]) for row in await cursor.fetchall()]
                if not event_ids:
                    return ()
                await connection.execute(
                    "UPDATE process_projection_outbox "
                    "SET attempts = attempts + 1, leased_until = %s "
                    "WHERE event_id = ANY(%s)",
                    (leased_until, event_ids),
                )
                rows = await connection.execute(
                    "SELECT event.*, outbox.attempts AS projection_attempts, "
                    "outbox.available_at AS projection_available_at, "
                    "outbox.leased_until AS projection_leased_until, "
                    "outbox.last_error AS projection_last_error "
                    "FROM process_projection_outbox AS outbox "
                    "JOIN process_event AS event USING (event_id) "
                    "WHERE outbox.event_id = ANY(%s) "
                    "ORDER BY outbox.available_at, outbox.event_id",
                    (event_ids,),
                )
                return tuple(_projection_job_from_row(row) for row in await rows.fetchall())

    async def complete_projection(self, event_id: str) -> None:
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                await connection.execute(
                    "DELETE FROM process_projection_outbox WHERE event_id = %s",
                    (event_id,),
                )

    async def retry_projection(
        self,
        event_id: str,
        *,
        available_at: datetime,
        last_error: str,
    ) -> None:
        if available_at.tzinfo is None:
            raise ValueError("available_at MUST be timezone-aware")
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                await connection.execute(
                    "UPDATE process_projection_outbox "
                    "SET available_at = %s, leased_until = NULL, last_error = %s "
                    "WHERE event_id = %s",
                    (available_at, last_error[:200], event_id),
                )

    async def list(
        self,
        *,
        workflow_ref: str | None = None,
        status: ProcessStatus | None = None,
        limit: int = 100,
    ) -> tuple[ProcessSnapshot, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit MUST be in [1, 1000]")
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                "SELECT * FROM process_runtime "
                "WHERE (%s IS NULL OR workflow_ref = %s) "
                "AND (%s IS NULL OR status = %s) "
                "ORDER BY updated_at DESC, process_id DESC LIMIT %s",
                (
                    workflow_ref,
                    workflow_ref,
                    status.value if status else None,
                    status.value if status else None,
                    limit,
                ),
            )
            return tuple(_snapshot_from_row(row) for row in await cursor.fetchall())

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _set_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        timeout = int(self._config.statement_timeout_ms)
        await connection.execute(f"SET LOCAL statement_timeout = {timeout}")

    async def _get_with_connection(
        self,
        connection: psycopg.AsyncConnection[Any],
        process_id: str,
    ) -> ProcessSnapshot | None:
        cursor = await connection.execute(
            "SELECT * FROM process_runtime WHERE process_id = %s",
            (process_id,),
        )
        row = await cursor.fetchone()
        return _snapshot_from_row(row) if row is not None else None

    async def _event_by_key(
        self,
        connection: psycopg.AsyncConnection[Any],
        key: str,
    ) -> ProcessEvent | None:
        cursor = await connection.execute(
            "SELECT * FROM process_event WHERE idempotency_key = %s",
            (key,),
        )
        row = await cursor.fetchone()
        return _event_from_row(row) if row is not None else None

    async def _insert_event(
        self,
        connection: psycopg.AsyncConnection[Any],
        event: ProcessEvent,
    ) -> None:
        await connection.execute(
            "INSERT INTO process_event "
            "(event_id, process_id, kind, idempotency_key, recorded_at, correlation_id, "
            "causation_id, step_id, attempt, payload) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
            (
                event.event_id,
                event.process_id,
                event.kind.value,
                event.idempotency_key,
                event.recorded_at,
                event.correlation_id,
                event.causation_id,
                event.step_id,
                event.attempt,
                json.dumps(dict(event.payload), default=str),
            ),
        )
        await connection.execute(
            "INSERT INTO process_projection_outbox "
            "(event_id, process_id, available_at) VALUES (%s, %s, %s) "
            "ON CONFLICT (event_id) DO NOTHING",
            (event.event_id, event.process_id, event.recorded_at),
        )


def _snapshot_from_row(row: Mapping[str, Any]) -> ProcessSnapshot:
    return ProcessSnapshot(
        process_id=str(row["process_id"]),
        workflow_ref=str(row["workflow_ref"]),
        workflow_version=str(row["workflow_version"]),
        status=ProcessStatus(str(row["status"])),
        current_step=str(row["current_step"]),
        target_resource_id=str(row["target_resource_id"]),
        started_at=_datetime(row["started_at"]),
        updated_at=_datetime(row["updated_at"]),
        correlation_id=str(row["correlation_id"]),
        revision=int(row["revision"]),
    )


def _event_from_row(row: Mapping[str, Any]) -> ProcessEvent:
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, Mapping):
        raise RuntimeError("process_event.payload MUST be a JSON object")
    return ProcessEvent(
        event_id=str(row["event_id"]),
        process_id=str(row["process_id"]),
        kind=ProcessEventKind(str(row["kind"])),
        idempotency_key=str(row["idempotency_key"]),
        recorded_at=_datetime(row["recorded_at"]),
        correlation_id=str(row["correlation_id"]),
        causation_id=str(row["causation_id"]) if row["causation_id"] is not None else None,
        step_id=str(row["step_id"]) if row["step_id"] is not None else None,
        attempt=int(row["attempt"]),
        payload=dict(payload),
    )


def _projection_job_from_row(row: Mapping[str, Any]) -> ProcessProjectionJob:
    leased_until = row["projection_leased_until"]
    last_error = row["projection_last_error"]
    return ProcessProjectionJob(
        event=_event_from_row(row),
        attempts=int(row["projection_attempts"]),
        available_at=_datetime(row["projection_available_at"]),
        leased_until=_datetime(leased_until) if leased_until is not None else None,
        last_error=str(last_error) if last_error is not None else None,
    )


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise RuntimeError(f"process timestamp has invalid type {type(value).__name__}")


__all__ = ["PostgresProcessRuntimeStore", "PostgresProcessRuntimeStoreConfig"]
