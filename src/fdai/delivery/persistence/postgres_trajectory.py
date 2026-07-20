"""PostgreSQL metadata and quarantine stores for trajectory datasets."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.trajectory import ExportQuarantineRecord
from fdai.shared.providers.trajectory import (
    TrajectoryDatasetRecord,
    TrajectoryDatasetState,
)

_COLUMNS: Final = (
    "dataset_id, purpose, access_scope, principal_scope_digest, state, schema_version, "
    "storage_ref, record_count, dataset_checksum, manifest_checksum, created_at, "
    "retention_until, deletion_due_at, legal_hold, legal_hold_ref, deleted_at"
)


@dataclass(frozen=True, slots=True)
class PostgresTrajectoryStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresTrajectoryStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresTrajectoryStoreConfig timeouts MUST be positive")


class PostgresTrajectoryDatasetStore:
    def __init__(self, *, config: PostgresTrajectoryStoreConfig) -> None:
        self._config = config

    async def put(self, record: TrajectoryDatasetRecord) -> TrajectoryDatasetRecord:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                f"INSERT INTO trajectory_dataset ({_COLUMNS}) "  # noqa: S608
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (dataset_id) DO NOTHING RETURNING dataset_id",
                _values(record),
            )
            created = await cursor.fetchone() is not None
        existing = await self.get(record.dataset_id, access_scope=record.access_scope)
        if existing is None or (not created and existing != record):
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
                f"SELECT {_COLUMNS} FROM trajectory_dataset "  # noqa: S608
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
            raise ValueError("trajectory dataset list limit MUST be in [1, 500]")
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM trajectory_dataset "  # noqa: S608
                "WHERE access_scope = %s AND purpose = %s "
                "ORDER BY created_at DESC, dataset_id LIMIT %s",
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
        if not 1 <= limit <= 5_000:
            raise ValueError("trajectory retention deletion limit MUST be in [1, 5000]")
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM trajectory_dataset "  # noqa: S608
                "WHERE state <> 'deleted' AND legal_hold = FALSE AND deletion_due_at <= %s "
                "ORDER BY deletion_due_at, dataset_id LIMIT %s",
                (now, limit),
            )
            return tuple(_row_to_record(row) for row in await cursor.fetchall())

    async def mark_deleted(
        self,
        dataset_id: str,
        *,
        deleted_at: datetime,
    ) -> TrajectoryDatasetRecord:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                f"UPDATE trajectory_dataset SET state = 'deleted', storage_ref = NULL, "  # noqa: S608
                f"deleted_at = %s WHERE dataset_id = %s AND legal_hold = FALSE "
                f"AND state <> 'deleted' RETURNING {_COLUMNS}",
                (deleted_at, dataset_id),
            )
            row = await cursor.fetchone()
            if row is not None:
                return _row_to_record(row)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM trajectory_dataset WHERE dataset_id = %s",  # noqa: S608
                (dataset_id,),
            )
            current = await cursor.fetchone()
        if current is None:
            raise LookupError(f"trajectory dataset was not found: {dataset_id}")
        record = _row_to_record(current)
        if record.legal_hold:
            raise PermissionError("trajectory dataset is under legal hold")
        if record.state is TrajectoryDatasetState.DELETED:
            return record
        raise RuntimeError("trajectory dataset deletion compare-and-set failed")

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


class PostgresTrajectoryQuarantineStore:
    def __init__(self, *, config: PostgresTrajectoryStoreConfig) -> None:
        self._config = config

    async def put(self, record: ExportQuarantineRecord) -> None:
        findings = sorted(f"{item.kind.value}:{item.code}" for item in record.findings)
        async with (
            await psycopg.AsyncConnection.connect(
                self._config.dsn,
                row_factory=dict_row,
                connect_timeout=self._config.connect_timeout_s,
            ) as connection,
            connection.transaction(),
        ):
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._config.statement_timeout_ms),),
            )
            await connection.execute(
                "INSERT INTO trajectory_export_quarantine "
                "(dataset_id, trajectory_id, finding_codes, quarantined_at) "
                "VALUES (%s, %s, %s::jsonb, %s) ON CONFLICT DO NOTHING",
                (record.dataset_id, record.trajectory_id, json.dumps(findings), datetime.now(UTC)),
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
    return TrajectoryDatasetRecord(
        dataset_id=str(row["dataset_id"]),
        purpose=str(row["purpose"]),
        access_scope=str(row["access_scope"]),
        principal_scope_digest=str(row["principal_scope_digest"]),
        state=TrajectoryDatasetState(str(row["state"])),
        schema_version=str(row["schema_version"]),
        storage_ref=str(row["storage_ref"]) if row["storage_ref"] is not None else None,
        record_count=int(row["record_count"]),
        dataset_checksum=(
            str(row["dataset_checksum"]) if row["dataset_checksum"] is not None else None
        ),
        manifest_checksum=(
            str(row["manifest_checksum"]) if row["manifest_checksum"] is not None else None
        ),
        created_at=row["created_at"],
        retention_until=row["retention_until"],
        deletion_due_at=row["deletion_due_at"],
        legal_hold=bool(row["legal_hold"]),
        legal_hold_ref=(str(row["legal_hold_ref"]) if row["legal_hold_ref"] is not None else None),
        deleted_at=row["deleted_at"],
    )


__all__ = [
    "PostgresTrajectoryDatasetStore",
    "PostgresTrajectoryQuarantineStore",
    "PostgresTrajectoryStoreConfig",
]
