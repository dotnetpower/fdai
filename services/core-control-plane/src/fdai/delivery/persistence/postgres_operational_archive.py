"""PostgreSQL append-only persistence for operational archive evidence."""

# ruff: noqa: S608 - table and column identifiers are fixed private call-site literals.

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai.core.ontology_platform.archive_manifest import (
    ArchiveManifest,
    ArchiveVerificationReceipt,
    archive_manifest_record,
)
from fdai.core.ontology_platform.archive_retention import (
    ArchiveCoverageReceipt,
    ArchiveRestoreReceipt,
    RetentionHold,
)
from fdai.delivery.operational_archive_purge import (
    ArchivePurgeReceipt,
    ArchivePurgeStatus,
)


@dataclass(frozen=True, slots=True)
class PostgresOperationalArchiveStoreConfig:
    """Configure bounded PostgreSQL archive evidence access."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("operational archive store DSN MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("operational archive store timeouts MUST be positive")


class PostgresOperationalArchiveStore:
    """Persist immutable manifests and every purge prerequisite receipt."""

    def __init__(self, *, config: PostgresOperationalArchiveStoreConfig) -> None:
        self._config = config

    async def put_manifest(self, manifest: ArchiveManifest) -> bool:
        """Insert one manifest or verify replay-identical durable content."""

        record = archive_manifest_record(manifest)
        created = await self._insert(
            "INSERT INTO operational_archive_manifest ("
            "manifest_digest, archive_content_digest, covered_start, covered_end, "
            "object_count, relationship_count, coverage_complete, record, created_at"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (manifest_digest) DO NOTHING RETURNING manifest_digest",
            (
                manifest.digest,
                manifest.archive_content_digest,
                manifest.covered_start,
                manifest.covered_end,
                manifest.object_count,
                manifest.relationship_count,
                manifest.coverage_complete,
                Jsonb(record),
                manifest.created_at,
            ),
        )
        if created:
            return True
        await self._require_same_record(
            "operational_archive_manifest",
            "manifest_digest",
            manifest.digest,
            record,
        )
        return False

    async def append_verification(self, receipt: ArchiveVerificationReceipt) -> bool:
        record = {
            "manifest_digest": receipt.manifest_digest,
            "verified": receipt.verified,
            "reason_codes": receipt.reason_codes,
            "verified_at": receipt.verified_at.isoformat(),
            "digest": receipt.digest,
        }
        return await self._append_digest_record(
            table="operational_archive_verification_receipt",
            digest_column="receipt_digest",
            digest=receipt.digest,
            columns=("manifest_digest", "verified", "reason_codes", "verified_at"),
            values=(
                receipt.manifest_digest,
                receipt.verified,
                Jsonb(receipt.reason_codes),
                receipt.verified_at,
            ),
            record=record,
        )

    async def append_restore(self, receipt: ArchiveRestoreReceipt) -> bool:
        record = {
            "manifest_digest": receipt.manifest_digest,
            "verification_receipt_digest": receipt.verification_receipt_digest,
            "sampled_partition_digests": receipt.sampled_partition_digests,
            "restored_object_count": receipt.restored_object_count,
            "restored_relationship_count": receipt.restored_relationship_count,
            "passed": receipt.passed,
            "reason_codes": receipt.reason_codes,
            "sampled_at": receipt.sampled_at.isoformat(),
            "digest": receipt.digest,
        }
        return await self._append_digest_record(
            table="operational_archive_restore_receipt",
            digest_column="receipt_digest",
            digest=receipt.digest,
            columns=(
                "manifest_digest",
                "verification_receipt_digest",
                "passed",
                "reason_codes",
                "sampled_at",
            ),
            values=(
                receipt.manifest_digest,
                receipt.verification_receipt_digest,
                receipt.passed,
                Jsonb(receipt.reason_codes),
                receipt.sampled_at,
            ),
            record=record,
        )

    async def append_coverage(self, receipt: ArchiveCoverageReceipt) -> bool:
        manifest_digests = tuple(item.manifest_digest for item in receipt.index.entries)
        record = {
            "coverage_start": receipt.index.coverage_start.isoformat(),
            "coverage_end": receipt.index.coverage_end.isoformat(),
            "complete": receipt.index.complete,
            "manifest_digests": manifest_digests,
            "recorded_at": receipt.recorded_at.isoformat(),
            "digest": receipt.digest,
        }
        return await self._append_digest_record(
            table="operational_archive_coverage_receipt",
            digest_column="receipt_digest",
            digest=receipt.digest,
            columns=(
                "coverage_start",
                "coverage_end",
                "complete",
                "manifest_digests",
                "recorded_at",
            ),
            values=(
                receipt.index.coverage_start,
                receipt.index.coverage_end,
                receipt.index.complete,
                Jsonb(manifest_digests),
                receipt.recorded_at,
            ),
            record=record,
        )

    async def append_hold(self, hold: RetentionHold, *, recorded_at: datetime) -> bool:
        """Append one hold placement; release remains a separate future event."""

        record = {
            "hold_id": hold.hold_id,
            "manifest_digest": hold.manifest_digest,
            "event_type": "placed",
            "hold_kind": hold.kind.value,
            "starts_at": hold.starts_at.isoformat(),
            "ends_at": hold.ends_at.isoformat() if hold.ends_at is not None else None,
            "recorded_at": recorded_at.isoformat(),
        }
        event_digest = _sha256(record)
        return await self._append_digest_record(
            table="operational_retention_hold_event",
            digest_column="event_digest",
            digest=event_digest,
            columns=(
                "hold_id",
                "manifest_digest",
                "event_type",
                "hold_kind",
                "starts_at",
                "ends_at",
                "recorded_at",
            ),
            values=(
                hold.hold_id,
                hold.manifest_digest,
                "placed",
                hold.kind.value,
                hold.starts_at,
                hold.ends_at,
                recorded_at,
            ),
            record={**record, "digest": event_digest},
        )

    async def append(self, receipt: ArchivePurgeReceipt) -> None:
        record = _purge_record(receipt)
        await self._append_digest_record(
            table="operational_archive_purge_receipt",
            digest_column="receipt_digest",
            digest=receipt.digest,
            columns=(
                "idempotency_key",
                "attempt",
                "manifest_digest",
                "status",
                "reason_codes",
                "source_data_preserved",
                "storage_pressure",
                "recorded_at",
            ),
            values=(
                receipt.idempotency_key,
                receipt.attempt,
                receipt.manifest_digest,
                receipt.status.value,
                Jsonb(receipt.reason_codes),
                receipt.source_data_preserved,
                receipt.storage_pressure,
                receipt.recorded_at,
            ),
            record=record,
        )

    async def latest(self, idempotency_key: str) -> ArchivePurgeReceipt | None:
        raw = await self._get_record(
            "SELECT record FROM operational_archive_purge_receipt "
            "WHERE idempotency_key = %s "
            "ORDER BY attempt DESC, "
            "CASE status WHEN 'pending' THEN 0 ELSE 1 END DESC, "
            "recorded_at DESC, receipt_digest DESC LIMIT 1",
            (idempotency_key,),
        )
        return None if raw is None else _purge_from_record(raw)

    async def _append_digest_record(
        self,
        *,
        table: str,
        digest_column: str,
        digest: str,
        columns: tuple[str, ...],
        values: tuple[object, ...],
        record: dict[str, object],
    ) -> bool:
        column_sql = ", ".join((digest_column, *columns, "record"))
        placeholders = ", ".join("%s" for _ in range(len(columns) + 2))
        created = await self._insert(
            f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders}) "
            f"ON CONFLICT ({digest_column}) DO NOTHING RETURNING {digest_column}",
            (digest, *values, Jsonb(record)),
        )
        if created:
            return True
        await self._require_same_record(table, digest_column, digest, record)
        return False

    async def _require_same_record(
        self,
        table: str,
        digest_column: str,
        digest: str,
        expected: dict[str, object],
    ) -> None:
        raw = await self._get_record(
            f"SELECT record FROM {table} WHERE {digest_column} = %s",
            (digest,),
        )
        if raw != expected:
            raise ValueError("operational archive digest conflicts with durable content")

    async def _insert(self, query: str, parameters: tuple[object, ...]) -> bool:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(query, parameters)
            return await cursor.fetchone() is not None

    async def _get_record(
        self,
        query: str,
        parameters: tuple[object, ...],
    ) -> dict[str, Any] | None:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(query, parameters)
            row = await cursor.fetchone()
        return None if row is None else row["record"]

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        dsn = self._config.dsn.replace("postgresql+psycopg://", "postgresql://", 1)
        return await psycopg.AsyncConnection.connect(
            dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _set_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _purge_record(receipt: ArchivePurgeReceipt) -> dict[str, object]:
    return {
        "idempotency_key": receipt.idempotency_key,
        "attempt": receipt.attempt,
        "manifest_digest": receipt.manifest_digest,
        "status": receipt.status.value,
        "reason_codes": receipt.reason_codes,
        "source_data_preserved": receipt.source_data_preserved,
        "storage_pressure": receipt.storage_pressure,
        "recorded_at": receipt.recorded_at.isoformat(),
        "digest": receipt.digest,
    }


def _purge_from_record(raw: dict[str, Any]) -> ArchivePurgeReceipt:
    return ArchivePurgeReceipt(
        idempotency_key=str(raw["idempotency_key"]),
        attempt=int(raw["attempt"]),
        manifest_digest=str(raw["manifest_digest"]),
        status=ArchivePurgeStatus(str(raw["status"])),
        reason_codes=tuple(str(item) for item in raw["reason_codes"]),
        source_data_preserved=bool(raw["source_data_preserved"]),
        storage_pressure=bool(raw["storage_pressure"]),
        recorded_at=datetime.fromisoformat(str(raw["recorded_at"])),
        digest=str(raw["digest"]),
    )


def _sha256(value: object) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
    )


__all__ = [
    "PostgresOperationalArchiveStore",
    "PostgresOperationalArchiveStoreConfig",
]
