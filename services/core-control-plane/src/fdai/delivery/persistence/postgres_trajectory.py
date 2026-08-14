"""PostgreSQL metadata persistence for governed trajectory datasets."""

# ruff: noqa: S608 - interpolated columns are fixed module constants; values are bound.

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.shared.providers.trajectory import TrajectoryDatasetRecord, TrajectoryDatasetState

_COLUMNS: Final = (
    "dataset_id, purpose, access_scope, principal_scope_digest, state, schema_version, "
    "storage_ref, record_count, dataset_checksum, manifest_checksum, created_at, "
    "retention_until, deletion_due_at, legal_hold, legal_hold_ref, deleted_at"
)


@dataclass(frozen=True, slots=True)
class PostgresTrajectoryDatasetStoreConfig:
    """Connection and statement bounds for trajectory metadata persistence."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("trajectory dataset store DSN MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("trajectory dataset store timeouts MUST be positive")


class PostgresTrajectoryDatasetStore:
    """Store access-scoped metadata and recheck legal hold before tombstoning."""

    def __init__(self, *, config: PostgresTrajectoryDatasetStoreConfig) -> None:
        self._config = config

    async def put(self, record: TrajectoryDatasetRecord) -> TrajectoryDatasetRecord:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                f"INSERT INTO trajectory_dataset ({_COLUMNS}) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                "%s, %s, %s) ON CONFLICT (dataset_id) DO NOTHING "
                f"RETURNING {_COLUMNS}",
                _values(record),
            )
            row = await cursor.fetchone()
            if row is not None:
                return _row_to_record(row)
            existing = await self._get(connection, record.dataset_id, lock=True)
            if existing is None or existing != record:
                raise ValueError("trajectory dataset id was reused with different metadata")
            return existing

    async def get(
        self,
        dataset_id: str,
        *,
        access_scope: str,
    ) -> TrajectoryDatasetRecord | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM trajectory_dataset "
                "WHERE dataset_id = %s AND access_scope = %s",
                (dataset_id, access_scope),
            )
            row = await cursor.fetchone()
        return _row_to_record(row) if row is not None else None

    async def list(
        self,
        *,
        access_scope: str,
        purpose: str,
        limit: int,
    ) -> tuple[TrajectoryDatasetRecord, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("trajectory dataset query limit MUST be in [1, 500]")
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM trajectory_dataset "
                "WHERE access_scope = %s AND purpose = %s "
                "ORDER BY created_at DESC, dataset_id DESC LIMIT %s",
                (access_scope, purpose, limit),
            )
            rows = await cursor.fetchall()
        return tuple(_row_to_record(row) for row in rows)

    async def list_due(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[TrajectoryDatasetRecord, ...]:
        _require_aware("trajectory retention time", now)
        if not 1 <= limit <= 5_000:
            raise ValueError("trajectory retention deletion limit MUST be in [1, 5000]")
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM trajectory_dataset "
                "WHERE state IN ('completed', 'deleting') AND legal_hold = FALSE "
                "AND deletion_due_at <= %s "
                "ORDER BY deletion_due_at, dataset_id LIMIT %s",
                (now, limit),
            )
            rows = await cursor.fetchall()
        return tuple(_row_to_record(row) for row in rows)

    async def place_legal_hold(self, *, dataset_id: str, hold_ref: str) -> bool | None:
        """Place one monotonic hold, returning whether durable state changed."""

        if not hold_ref or len(hold_ref) > 512 or any(ord(char) < 32 for char in hold_ref):
            raise ValueError("trajectory dataset legal hold reference MUST be bounded text")
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            record = await self._get(connection, dataset_id, lock=True)
            if record is None:
                return None
            if record.state in (
                TrajectoryDatasetState.DELETING,
                TrajectoryDatasetState.DELETED,
            ):
                raise ValueError(
                    "deleting or deleted trajectory dataset cannot be placed under legal hold"
                )
            if record.legal_hold:
                if record.legal_hold_ref != hold_ref:
                    raise ValueError("trajectory dataset already has a different legal hold")
                return False
            await connection.execute(
                "UPDATE trajectory_dataset SET legal_hold = TRUE, legal_hold_ref = %s "
                "WHERE dataset_id = %s",
                (hold_ref, dataset_id),
            )
            return True

    async def claim_deletion(
        self,
        dataset_id: str,
        *,
        now: datetime,
    ) -> TrajectoryDatasetRecord | None:
        _require_aware("trajectory retention time", now)
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "UPDATE trajectory_dataset SET state = 'deleting' "
                "WHERE dataset_id = %s AND state = 'completed' AND legal_hold = FALSE "
                f"AND deletion_due_at <= %s RETURNING {_COLUMNS}",
                (dataset_id, now),
            )
            row = await cursor.fetchone()
            if row is None:
                existing = await connection.execute(
                    f"SELECT {_COLUMNS} FROM trajectory_dataset WHERE dataset_id = %s "
                    "AND state = 'deleting' AND legal_hold = FALSE AND deletion_due_at <= %s",
                    (dataset_id, now),
                )
                row = await existing.fetchone()
        return _row_to_record(row) if row is not None else None

    async def mark_deleted(
        self,
        dataset_id: str,
        *,
        deleted_at: datetime,
    ) -> TrajectoryDatasetRecord:
        _require_aware("trajectory deletion time", deleted_at)
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "UPDATE trajectory_dataset SET state = 'deleted', storage_ref = NULL, "
                "deleted_at = %s WHERE dataset_id = %s AND state = 'deleting' "
                f"AND legal_hold = FALSE RETURNING {_COLUMNS}",
                (deleted_at, dataset_id),
            )
            row = await cursor.fetchone()
            if row is None:
                existing = await connection.execute(
                    f"SELECT {_COLUMNS} FROM trajectory_dataset WHERE dataset_id = %s",
                    (dataset_id,),
                )
                row = await existing.fetchone()
        if row is None:
            raise LookupError(f"trajectory dataset was not found: {dataset_id}")
        record = _row_to_record(row)
        if record.legal_hold:
            raise PermissionError("trajectory dataset is under legal hold")
        if record.state is not TrajectoryDatasetState.DELETED:
            raise RuntimeError("trajectory dataset deletion state changed concurrently")
        return record

    async def _get(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        dataset_id: str,
        *,
        lock: bool,
    ) -> TrajectoryDatasetRecord | None:
        cursor = await connection.execute(
            f"SELECT {_COLUMNS} FROM trajectory_dataset WHERE dataset_id = %s"
            + (" FOR UPDATE" if lock else ""),
            (dataset_id,),
        )
        row = await cursor.fetchone()
        return _row_to_record(row) if row is not None else None

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        dsn = self._config.dsn.replace("postgresql+psycopg://", "postgresql://", 1)
        return await psycopg.AsyncConnection.connect(
            dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _values(record: TrajectoryDatasetRecord) -> tuple[object, ...]:
    return (
        record.dataset_id,
        record.purpose,
        record.access_scope,
        record.principal_scope_digest,
        record.state.value,
        record.schema_version,
        record.storage_ref,
        record.record_count,
        record.dataset_checksum,
        record.manifest_checksum,
        record.created_at,
        record.retention_until,
        record.deletion_due_at,
        record.legal_hold,
        record.legal_hold_ref,
        record.deleted_at,
    )


def _row_to_record(row: dict[str, Any]) -> TrajectoryDatasetRecord:
    legal_hold = row["legal_hold"]
    record_count = row["record_count"]
    if type(legal_hold) is not bool:
        raise ValueError("trajectory dataset legal_hold MUST be a boolean")
    if type(record_count) is not int:
        raise ValueError("trajectory dataset record_count MUST be an integer")
    return TrajectoryDatasetRecord(
        dataset_id=str(row["dataset_id"]),
        purpose=str(row["purpose"]),
        access_scope=str(row["access_scope"]),
        principal_scope_digest=str(row["principal_scope_digest"]),
        state=TrajectoryDatasetState(str(row["state"])),
        schema_version=str(row["schema_version"]),
        storage_ref=_optional_str(row["storage_ref"]),
        record_count=record_count,
        dataset_checksum=_optional_str(row["dataset_checksum"]),
        manifest_checksum=_optional_str(row["manifest_checksum"]),
        created_at=row["created_at"],
        retention_until=row["retention_until"],
        deletion_due_at=row["deletion_due_at"],
        legal_hold=legal_hold,
        legal_hold_ref=_optional_str(row["legal_hold_ref"]),
        deleted_at=row["deleted_at"],
    )


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None else None


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} MUST include timezone")


__all__ = ["PostgresTrajectoryDatasetStore", "PostgresTrajectoryDatasetStoreConfig"]
