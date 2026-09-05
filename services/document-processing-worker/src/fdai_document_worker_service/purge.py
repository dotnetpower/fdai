"""Independent purge-verification seams and production residue verifier."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

import psycopg
from fdai_service_contracts import DocumentPurgeVerificationReceipt


class ArtifactResidueProbe(Protocol):
    """Read artifact existence without sharing the cleanup operation."""

    async def artifact_exists(self, document_id: UUID, version_id: UUID) -> bool: ...


class SourceResidueProbe(Protocol):
    """Read source existence without changing source storage."""

    async def source_exists(self, object_key: str) -> bool: ...


class DocumentPurgeVerifier(Protocol):
    """Independently verify all worker-owned document residue after cleanup."""

    async def verify(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        source_object_keys: Sequence[str],
    ) -> DocumentPurgeVerificationReceipt: ...


class PurgeVerificationError(RuntimeError):
    """Raised when cleanup cannot prove a zero-residue terminal outcome."""


class PostgresDocumentPurgeVerifier:
    """Verify index and legal-hold state in PostgreSQL plus both object stores."""

    def __init__(
        self,
        *,
        dsn: str,
        artifacts: ArtifactResidueProbe,
        sources: SourceResidueProbe,
        backup_blocked: bool = False,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._dsn = dsn
        self._artifacts = artifacts
        self._sources = sources
        self._backup_blocked = backup_blocked
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def verify(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        source_object_keys: Sequence[str],
    ) -> DocumentPurgeVerificationReceipt:
        """Generate a receipt from fresh authoritative reads after cleanup."""
        doc_id = f"governed:{document_id}:{version_id}"
        async with await psycopg.AsyncConnection.connect(self._dsn) as connection:
            index_row = await (
                await connection.execute(
                    "SELECT count(*) FROM knowledge_chunk WHERE doc_id = %s",
                    (doc_id,),
                )
            ).fetchone()
            version_row = await (
                await connection.execute(
                    "SELECT upload_id, "
                    "COALESCE((payload->'retention'->>'legal_hold')::boolean, FALSE) "
                    "FROM document_version WHERE document_id = %s AND version_id = %s",
                    (document_id, version_id),
                )
            ).fetchone()
            producer_row = (
                None
                if version_row is None
                else await (
                    await connection.execute(
                        "SELECT 1 FROM document_worker_claim "
                        "WHERE upload_id = %s AND stage <> 'deletion' AND status = 'active' "
                        "AND lease_expires_at > clock_timestamp() LIMIT 1",
                        (version_row[0],),
                    )
                ).fetchone()
            )
        if index_row is None or version_row is None:
            raise PurgeVerificationError("purge verification could not read authoritative state")
        derivative_objects = int(await self._artifacts.artifact_exists(document_id, version_id))
        source_objects = 0
        for object_key in sorted(set(source_object_keys)):
            source_objects += int(await self._sources.source_exists(object_key))
        return DocumentPurgeVerificationReceipt(
            document_id=document_id,
            version_id=version_id,
            live_index_rows=int(index_row[0]),
            derivative_objects=derivative_objects,
            source_objects=source_objects,
            cache_entries=0,
            legal_hold_blocked=bool(version_row[1]),
            backup_blocked=self._backup_blocked,
            producer_blocked=producer_row is not None,
            verified_at=self._clock(),
        )
