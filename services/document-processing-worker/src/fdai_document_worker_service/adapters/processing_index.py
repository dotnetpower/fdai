"""PostgreSQL vector index lifecycle for processed documents."""

from __future__ import annotations

import json
from collections.abc import Sequence
from uuid import UUID

import psycopg
from fdai_service_contracts import (
    DocumentEnvelope,
    DocumentIndexState,
    DocumentLifecycleConflictError,
    DocumentState,
    DocumentVersion,
)
from fdai_service_contracts.cloud_knowledge import content_digest

from fdai_document_worker_service.adapters.processing_azure import EmbeddingModel


class PgvectorDocumentIndex:
    """Atomically replace the chunks for one immutable document version."""

    def __init__(
        self,
        *,
        dsn: str,
        embedder: EmbeddingModel | None,
        dimension: int,
        max_chars: int = 1200,
        overlap: int = 150,
    ) -> None:
        self._dsn = dsn
        self._embedder = embedder
        self._dimension = dimension
        self._max_chars = max_chars
        self._overlap = overlap

    async def commit(self, envelope: DocumentEnvelope) -> int:
        rows: list[tuple[str, str, str, str, str | None, str]] = []
        doc_id = _document_ref(envelope.document_id, envelope.version_id)
        for unit in envelope.units:
            pieces = (
                (unit.text,)
                if envelope.cloud_knowledge
                else _chunks(unit.text, self._max_chars, self._overlap)
            )
            for index, text in enumerate(pieces):
                # Cloud-reference v1 is explicitly lexical-only, including disconnected venues.
                vector = (
                    None
                    if envelope.cloud_knowledge or self._embedder is None
                    else await self._embedder.embed(text)
                )
                chunk_id = f"{doc_id}:{unit.unit_id}:{index}"
                metadata = {
                    "governed_document": "true",
                    "document_id": str(envelope.document_id),
                    "version_id": str(envelope.version_id),
                    "collection_id": envelope.collection_id,
                    "access_descriptor_ref": envelope.access_descriptor_ref,
                    "locator": unit.locator,
                    "disposition": (
                        envelope.artifact_manifest.disposition.value
                        if envelope.artifact_manifest is not None
                        else "governed_knowledge"
                    ),
                    "scope_kind": (
                        envelope.artifact_manifest.scope_kind.value
                        if envelope.artifact_manifest is not None
                        and envelope.artifact_manifest.scope_kind is not None
                        else "collection"
                    ),
                    "scope_ref": (
                        envelope.artifact_manifest.scope_ref
                        if envelope.artifact_manifest is not None
                        else envelope.collection_id
                    ),
                    "retention_state": "building",
                    "expires_at": (
                        envelope.artifact_manifest.retention.derived_expires_at.isoformat()
                        if envelope.artifact_manifest is not None
                        and envelope.artifact_manifest.retention.derived_expires_at is not None
                        else None
                    ),
                }
                if envelope.cloud_knowledge is not None:
                    binding = envelope.cloud_knowledge
                    source = next(
                        (
                            item
                            for item in binding.sources
                            if unit.locator.startswith(
                                f"cloud:{content_digest(item.source_id.encode())[:16]}:"
                            )
                        ),
                        None,
                    )
                    if source is None:
                        raise ValueError("cloud knowledge unit lost its source identity")
                    metadata.update(
                        {
                            "cloud_source": source.model_dump_json(),
                            "cloud_registry_digest": binding.registry_digest,
                            "cloud_manifest_digest": binding.manifest_digest,
                            "cloud_admission_expires_at": binding.admission_expires_at.isoformat(),
                            "retrieval_mode": "lexical",
                        }
                    )
                rows.append(
                    (
                        chunk_id,
                        doc_id,
                        text,
                        f"document://{envelope.document_id}/versions/{envelope.version_id}#{unit.unit_id}",
                        _vector(vector, self._dimension) if vector is not None else None,
                        json.dumps(metadata, sort_keys=True),
                    )
                )
        async with (
            await psycopg.AsyncConnection.connect(self._dsn) as connection,
            connection.transaction(),
        ):
            version_row = await (
                await connection.execute(
                    "SELECT payload FROM document_version "
                    "WHERE document_id = %s AND version_id = %s FOR UPDATE",
                    (envelope.document_id, envelope.version_id),
                )
            ).fetchone()
            if version_row is None:
                raise DocumentLifecycleConflictError("document index version is unavailable")
            version = DocumentVersion.model_validate(version_row[0])
            if (
                version.state is not DocumentState.INDEXING
                or version.index_state is not DocumentIndexState.BUILDING
                or version.active
                or version.available
            ):
                raise DocumentLifecycleConflictError(
                    "document index commit requires the current building version"
                )
            await connection.execute("DELETE FROM knowledge_chunk WHERE doc_id = %s", (doc_id,))
            for row in rows:
                await connection.execute(
                    "INSERT INTO knowledge_chunk "
                    "(chunk_id, doc_id, text, source_ref, embedding, metadata) "
                    "VALUES (%s, %s, %s, %s, %s::vector, %s::jsonb) "
                    "ON CONFLICT (chunk_id) DO UPDATE SET text=EXCLUDED.text, "
                    "source_ref=EXCLUDED.source_ref, embedding=EXCLUDED.embedding, "
                    "metadata=EXCLUDED.metadata",
                    row,
                )
        return len(rows)

    async def activate(self, document_id: UUID, version_id: UUID) -> None:
        """Expose staged chunks only after authoritative READY/ACTIVE metadata."""
        async with (
            await psycopg.AsyncConnection.connect(self._dsn) as connection,
            connection.transaction(),
        ):
            version_row = await (
                await connection.execute(
                    "SELECT payload FROM document_version "
                    "WHERE document_id = %s AND version_id = %s FOR UPDATE",
                    (document_id, version_id),
                )
            ).fetchone()
            if version_row is None:
                raise DocumentLifecycleConflictError("document index version is unavailable")
            version = DocumentVersion.model_validate(version_row[0])
            if (
                version.state not in {DocumentState.READY, DocumentState.READY_WITH_WARNINGS}
                or version.index_state is not DocumentIndexState.ACTIVE
                or not version.active
                or not version.available
            ):
                raise DocumentLifecycleConflictError(
                    "document index activation requires the current ready version"
                )
            await connection.execute(
                "UPDATE knowledge_chunk "
                "SET metadata = jsonb_set(metadata, '{retention_state}', '\"live\"'::jsonb) "
                "WHERE doc_id = %s",
                (_document_ref(document_id, version_id),),
            )

    async def tombstone(self, document_id: UUID, version_id: UUID) -> None:
        """Remove chunks from retrieval for active or legacy terminal deletion."""
        async with (
            await psycopg.AsyncConnection.connect(self._dsn) as connection,
            connection.transaction(),
        ):
            version_row = await (
                await connection.execute(
                    "SELECT payload FROM document_version "
                    "WHERE document_id = %s AND version_id = %s FOR UPDATE",
                    (document_id, version_id),
                )
            ).fetchone()
            if version_row is None:
                raise DocumentLifecycleConflictError("document index version is unavailable")
            version = DocumentVersion.model_validate(version_row[0])
            deletion_metadata_valid = version.state is DocumentState.DELETED or (
                version.state is DocumentState.DELETING
                and version.index_state is DocumentIndexState.TOMBSTONED
            )
            if not deletion_metadata_valid or version.active or version.available:
                raise DocumentLifecycleConflictError(
                    "document index tombstone requires authoritative deletion metadata"
                )
            await connection.execute(
                "UPDATE knowledge_chunk "
                "SET metadata = jsonb_set(metadata, '{retention_state}', '\"tombstoned\"'::jsonb) "
                "WHERE doc_id = %s",
                (_document_ref(document_id, version_id),),
            )

    async def delete(self, document_id: UUID, version_id: UUID) -> None:
        async with await psycopg.AsyncConnection.connect(self._dsn) as connection:
            await connection.execute(
                "DELETE FROM knowledge_chunk WHERE doc_id = %s",
                (_document_ref(document_id, version_id),),
            )


def _chunks(text: str, max_chars: int, overlap: int) -> tuple[str, ...]:
    if not text:
        return ()
    values: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        values.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return tuple(values)


def _document_ref(document_id: UUID, version_id: UUID) -> str:
    return f"governed:{document_id}:{version_id}"


def _vector(values: Sequence[float], dimension: int) -> str:
    if len(values) != dimension:
        raise ValueError("embedding vector dimension mismatch")
    return "[" + ",".join(format(float(value), ".12g") for value in values) + "]"
