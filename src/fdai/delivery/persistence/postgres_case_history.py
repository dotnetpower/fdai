"""Relational PostgreSQL authority for case-history metadata and revisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai.shared.providers.case_history import CaseHistoryRevisionRecord

_SELECT_LATEST = """
SELECT c.*, r.manifest_digest, r.parent_manifest_digest, r.source_set_digest,
       r.storage_ref AS revision_storage_ref, r.artifact_size AS revision_artifact_size,
    r.event_time_cutoff, r.created_by_agent, r.sealed_at,
    r.metadata AS revision_metadata
  FROM case_history c
  JOIN case_history_revision r
    ON r.case_id = c.case_id AND r.revision = c.latest_revision
"""


@dataclass(frozen=True, slots=True)
class PostgresCaseHistoryMetadataStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("case history Postgres DSN MUST be non-empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("case history Postgres timeouts MUST be positive")


class PostgresCaseHistoryMetadataStore:
    def __init__(self, *, config: PostgresCaseHistoryMetadataStoreConfig) -> None:
        self._config = config

    async def verify_schema(self) -> None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            for table in ("case_history", "case_history_revision", "case_history_chunk"):
                await connection.execute(f"SELECT 1 FROM {table} LIMIT 0")  # noqa: S608

    async def verify_read_cutover(self) -> None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT status, mismatch_count FROM case_history_migration_state "
                "WHERE singleton = TRUE"
            )
            row = await cursor.fetchone()
            if row is None or row["status"] != "verified" or int(row["mismatch_count"]) != 0:
                raise RuntimeError("case history relational read cutover is not verified")

    async def record_backfill_result(self, *, mismatch_count: int, verified_at: datetime) -> None:
        if mismatch_count < 0 or verified_at.tzinfo is None:
            raise ValueError("case history backfill result is invalid")
        status = "verified" if mismatch_count == 0 else "pending"
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            await connection.execute(
                "UPDATE case_history_migration_state SET status = %s, mismatch_count = %s, "
                "verified_at = %s WHERE singleton = TRUE",
                (status, mismatch_count, verified_at if mismatch_count == 0 else None),
            )

    async def backfill_tombstone(self, record: CaseHistoryRevisionRecord) -> bool:
        if record.deleted_at is None or record.storage_ref is not None or record.artifact_size != 0:
            raise ValueError("case history backfill tombstone is invalid")
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            existing = await self._latest_locked(connection, record.case_id)
            if existing is not None:
                if existing != record:
                    raise ValueError("case history tombstone backfill conflict")
                return False
            await self._insert_case(connection, record)
            await self._insert_revision(connection, record)
            return True

    async def append_revision(self, record: CaseHistoryRevisionRecord) -> bool:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            current = await self._latest_locked(connection, record.case_id)
            if current is None:
                if record.revision != 1 or record.parent_manifest_digest is not None:
                    raise ValueError("case history revision or parent conflict")
                await self._insert_case(connection, record)
                await self._insert_revision(connection, record)
                return True
            duplicate = _validate_transition(current, record)
            if duplicate:
                return False
            await self._insert_revision(connection, record)
            cursor = await connection.execute(
                "UPDATE case_history SET latest_revision = %s, latest_manifest_digest = %s, "
                "state_revision = %s, detector_id = %s, detector_version = %s, metric = %s, "
                "outcome_label = %s, metadata = %s, retention_until = %s, deletion_due_at = %s, "
                "legal_hold = %s, legal_hold_ref = %s, updated_at = %s "
                "WHERE case_id = %s AND state_revision = %s",
                (
                    record.revision,
                    record.manifest_digest,
                    record.state_revision,
                    record.detector_id,
                    record.detector_version,
                    record.metric,
                    record.outcome_label,
                    Jsonb(dict(record.metadata)),
                    record.retention_until,
                    record.deletion_due_at,
                    record.legal_hold,
                    record.legal_hold_ref,
                    record.sealed_at,
                    record.case_id,
                    current.state_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("case history compare-and-set lost a concurrent revision")
            return True

    async def latest(
        self,
        case_id: str,
        *,
        access_scope_digest: str,
    ) -> CaseHistoryRevisionRecord | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"{_SELECT_LATEST} WHERE c.case_id = %s AND c.access_scope_digest = %s",
                (case_id, access_scope_digest),
            )
            row = await cursor.fetchone()
            return _record(row) if row is not None else None

    async def list_closed(
        self,
        *,
        access_scope_digest: str,
        purpose: str,
        outcome_labels: tuple[str, ...],
        detector_id: str | None = None,
        metric: str | None = None,
        limit: int,
    ) -> tuple[CaseHistoryRevisionRecord, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("case history list limit MUST be in [1, 500]")
        labels = list(outcome_labels) if outcome_labels else None
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"{_SELECT_LATEST} WHERE c.access_scope_digest = %s AND c.purpose = %s "
                "AND c.deleted_at IS NULL AND c.deletion_started_at IS NULL "
                "AND (%s::text[] IS NULL OR c.outcome_label = ANY(%s::text[])) "
                "AND (%s::text IS NULL OR c.detector_id = %s) "
                "AND (%s::text IS NULL OR c.metric = %s) "
                "ORDER BY r.sealed_at DESC, c.case_id LIMIT %s",
                (
                    access_scope_digest,
                    purpose,
                    labels,
                    labels,
                    detector_id,
                    detector_id,
                    metric,
                    metric,
                    limit,
                ),
            )
            return tuple(_record(row) for row in await cursor.fetchall())

    async def list_due(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[CaseHistoryRevisionRecord, ...]:
        if not 1 <= limit <= 5_000:
            raise ValueError("case history retention limit MUST be in [1, 5000]")
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"{_SELECT_LATEST} WHERE c.deleted_at IS NULL AND c.legal_hold = FALSE "
                "AND c.deletion_due_at <= %s ORDER BY c.deletion_due_at, c.case_id LIMIT %s",
                (now, limit),
            )
            return tuple(_record(row) for row in await cursor.fetchall())

    async def mark_deletion_started(
        self,
        case_id: str,
        *,
        access_scope_digest: str,
        revision: int,
        storage_refs: tuple[str, ...],
        started_at: datetime,
    ) -> CaseHistoryRevisionRecord:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            current = await self._required_locked(connection, case_id, access_scope_digest)
            if current.legal_hold:
                raise PermissionError("case history is under legal hold")
            if current.revision != revision:
                raise ValueError("case history deletion revision conflict")
            if current.deleted_at is not None:
                return current
            if current.deletion_started_at is not None:
                if current.deletion_storage_refs != storage_refs:
                    raise ValueError("case history deletion intent artifact conflict")
                return current
            await connection.execute(
                "UPDATE case_history SET deletion_started_at = %s, deletion_storage_refs = %s, "
                "state_revision = state_revision + 1, updated_at = %s WHERE case_id = %s",
                (started_at, list(storage_refs), started_at, case_id),
            )
            refreshed = await self._latest_locked(connection, case_id)
            if refreshed is None:
                raise RuntimeError("case history deletion intent lost its record")
            return refreshed

    async def mark_deleted(
        self,
        case_id: str,
        *,
        access_scope_digest: str,
        revision: int,
        deleted_at: datetime,
    ) -> CaseHistoryRevisionRecord:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            current = await self._required_locked(connection, case_id, access_scope_digest)
            if current.legal_hold:
                raise PermissionError("case history is under legal hold")
            if current.revision != revision:
                raise ValueError("case history deletion revision conflict")
            if current.deleted_at is not None:
                return current
            if current.deletion_started_at is None:
                raise ValueError("case history deletion intent is missing")
            await connection.execute(
                "UPDATE case_history SET deleted_at = %s, deletion_storage_refs = '{}', "
                "state_revision = state_revision + 1, updated_at = %s WHERE case_id = %s",
                (deleted_at, deleted_at, case_id),
            )
            await connection.execute(
                "UPDATE case_history_chunk SET deleted_at = %s "
                "WHERE case_id = %s AND deleted_at IS NULL",
                (deleted_at, case_id),
            )
            refreshed = await self._latest_locked(connection, case_id)
            if refreshed is None:
                raise RuntimeError("case history deletion lost its record")
            return refreshed

    async def _required_locked(
        self,
        connection: psycopg.AsyncConnection[Any],
        case_id: str,
        access_scope_digest: str,
    ) -> CaseHistoryRevisionRecord:
        current = await self._latest_locked(connection, case_id)
        if current is None or current.access_scope_digest != access_scope_digest:
            raise LookupError("case history was not found")
        return current

    async def _latest_locked(
        self,
        connection: psycopg.AsyncConnection[Any],
        case_id: str,
    ) -> CaseHistoryRevisionRecord | None:
        cursor = await connection.execute(
            f"{_SELECT_LATEST} WHERE c.case_id = %s FOR UPDATE OF c",
            (case_id,),
        )
        row = await cursor.fetchone()
        return _record(row) if row is not None else None

    async def _insert_case(
        self,
        connection: psycopg.AsyncConnection[Any],
        record: CaseHistoryRevisionRecord,
    ) -> None:
        await connection.execute(
            "INSERT INTO case_history (case_id, kind, correlation_id, purpose, "
            "access_scope_digest, latest_revision, latest_manifest_digest, state_revision, "
            "detector_id, detector_version, metric, outcome_label, metadata, retention_until, "
            "deletion_due_at, legal_hold, legal_hold_ref, deletion_started_at, "
            "deletion_storage_refs, deleted_at, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s)",
            (
                record.case_id,
                record.kind,
                record.correlation_id,
                record.purpose,
                record.access_scope_digest,
                record.revision,
                record.manifest_digest,
                record.state_revision,
                record.detector_id,
                record.detector_version,
                record.metric,
                record.outcome_label,
                Jsonb(dict(record.metadata)),
                record.retention_until,
                record.deletion_due_at,
                record.legal_hold,
                record.legal_hold_ref,
                record.deletion_started_at,
                list(record.deletion_storage_refs),
                record.deleted_at,
                record.sealed_at,
                record.sealed_at,
            ),
        )

    async def _insert_revision(
        self,
        connection: psycopg.AsyncConnection[Any],
        record: CaseHistoryRevisionRecord,
    ) -> None:
        await connection.execute(
            "INSERT INTO case_history_revision (case_id, revision, manifest_digest, "
            "parent_manifest_digest, source_set_digest, storage_ref, artifact_size, "
            "outcome_label, detector_id, detector_version, metric, metadata, event_time_cutoff, "
            "created_by_agent, sealed_at) VALUES "
            "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                record.case_id,
                record.revision,
                record.manifest_digest,
                record.parent_manifest_digest,
                record.source_set_digest,
                record.storage_ref
                or f"case-history/{record.case_id}/{record.revision}/{record.manifest_digest}.json",
                record.artifact_size,
                record.outcome_label,
                record.detector_id,
                record.detector_version,
                record.metric,
                Jsonb(dict(record.metadata)),
                record.event_time_cutoff,
                record.created_by_agent,
                record.sealed_at,
            ),
        )

    async def _connect(self) -> psycopg.AsyncConnection[Any]:
        return await psycopg.AsyncConnection.connect(
            _psycopg_dsn(self._config.dsn),
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _validate_transition(
    existing: CaseHistoryRevisionRecord,
    incoming: CaseHistoryRevisionRecord,
) -> bool:
    if existing.access_scope_digest != incoming.access_scope_digest:
        raise PermissionError("case history access scope cannot change")
    if existing.purpose != incoming.purpose:
        raise ValueError("case history purpose cannot change")
    if existing.deleted_at is not None:
        raise PermissionError("deleted case history cannot accept revisions")
    if existing.deletion_started_at is not None:
        raise PermissionError("case history pending deletion cannot accept revisions")
    if existing.source_set_digest == incoming.source_set_digest:
        if existing != incoming:
            raise ValueError("case history source set was reused with different metadata")
        return True
    if (
        incoming.revision != existing.revision + 1
        or incoming.state_revision != existing.state_revision + 1
        or incoming.parent_manifest_digest != existing.manifest_digest
    ):
        raise ValueError("case history revision or parent conflict")
    return False


def _record(row: dict[str, Any]) -> CaseHistoryRevisionRecord:
    deleted_at = row["deleted_at"]
    return CaseHistoryRevisionRecord(
        case_id=str(row["case_id"]),
        revision=int(row["latest_revision"]),
        kind=str(row["kind"]),
        correlation_id=str(row["correlation_id"]),
        purpose=str(row["purpose"]),
        access_scope_digest=str(row["access_scope_digest"]),
        manifest_digest=str(row["manifest_digest"]),
        parent_manifest_digest=(
            str(row["parent_manifest_digest"]) if row["parent_manifest_digest"] else None
        ),
        source_set_digest=str(row["source_set_digest"]),
        storage_ref=(None if deleted_at else str(row["revision_storage_ref"])),
        artifact_size=(0 if deleted_at else int(row["revision_artifact_size"])),
        outcome_label=str(row["outcome_label"]),
        detector_id=(str(row["detector_id"]) if row["detector_id"] is not None else None),
        detector_version=(
            str(row["detector_version"]) if row["detector_version"] is not None else None
        ),
        metric=(str(row["metric"]) if row["metric"] is not None else None),
        metadata=_metadata(row["revision_metadata"]),
        event_time_cutoff=row["event_time_cutoff"],
        created_by_agent=str(row["created_by_agent"]),
        sealed_at=row["sealed_at"],
        retention_until=row["retention_until"],
        deletion_due_at=row["deletion_due_at"],
        legal_hold=bool(row["legal_hold"]),
        legal_hold_ref=(str(row["legal_hold_ref"]) if row["legal_hold_ref"] else None),
        deleted_at=deleted_at,
        state_revision=int(row["state_revision"]),
        deletion_started_at=row["deletion_started_at"],
        deletion_storage_refs=tuple(row["deletion_storage_refs"]),
    )


def _psycopg_dsn(value: str) -> str:
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _metadata(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()
    ):
        raise ValueError("case history relational metadata MUST be a string mapping")
    return tuple(sorted(value.items()))


__all__ = ["PostgresCaseHistoryMetadataStore", "PostgresCaseHistoryMetadataStoreConfig"]
