"""Service-owned durable source checkpoints, fenced claims, and immutable check history."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import psycopg
from fdai_service_contracts.cloud_knowledge import canonical_bytes, content_digest

from fdai_ingestion_api_service.cloud_knowledge.collector import SourceState


@dataclass(frozen=True, slots=True)
class SourceCheckpoint:
    revision: int
    state: SourceState


class PostgresCloudKnowledgeStore:
    """Keep source caches separate from approved document/index state.

    All updates require the same unexpired server-clock lease and revision.
    Original attempt receipts are append-only. This store cannot activate a document.
    """

    def __init__(self, *, dsn: str) -> None:
        self._dsn = dsn

    async def readiness(self) -> None:
        async with await psycopg.AsyncConnection.connect(self._dsn, connect_timeout=5) as conn:
            await conn.execute("SELECT source_id FROM document_knowledge_source LIMIT 0")
            await conn.execute("SELECT digest FROM document_knowledge_check LIMIT 0")
            await conn.execute("SELECT manifest_digest FROM document_knowledge_release LIMIT 0")

    async def get(self, registry_digest: str, source_id: str) -> SourceCheckpoint:
        async with await psycopg.AsyncConnection.connect(self._dsn, connect_timeout=5) as conn:
            row = await (
                await conn.execute(
                    "SELECT revision, payload FROM document_knowledge_source "
                    "WHERE registry_digest = %s AND source_id = %s",
                    (registry_digest, source_id),
                )
            ).fetchone()
        return (
            SourceCheckpoint(0, SourceState())
            if row is None
            else SourceCheckpoint(
                int(row[0]),
                SourceState.model_validate(row[1]),
            )
        )

    async def claim(self, registry_digest: str, source_id: str, revision: int) -> UUID | None:
        claim = uuid4()
        async with await psycopg.AsyncConnection.connect(self._dsn, connect_timeout=5) as conn:
            await conn.execute("SET LOCAL lock_timeout = '3s'")
            await conn.execute(
                "INSERT INTO document_knowledge_source (registry_digest, source_id) "
                "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (registry_digest, source_id),
            )
            row = await (
                await conn.execute(
                    "UPDATE document_knowledge_source SET claim_id = %s, "
                    "lease_until = clock_timestamp() + interval '60 seconds' "
                    "WHERE registry_digest = %s AND source_id = %s AND revision = %s "
                    "AND (lease_until IS NULL OR lease_until < clock_timestamp()) "
                    "RETURNING source_id",
                    (claim, registry_digest, source_id, revision),
                )
            ).fetchone()
        return claim if row else None

    async def finish(
        self,
        registry_digest: str,
        source_id: str,
        checkpoint: SourceCheckpoint,
        claim: UUID,
        state: SourceState,
    ) -> None:
        if state.last_attempt is None:
            raise ValueError("source completion requires an immutable attempt receipt")
        receipt = state.last_attempt
        if receipt.source_id != source_id:
            raise ValueError("source receipt identity changed")
        digest = content_digest(canonical_bytes(receipt))
        async with await psycopg.AsyncConnection.connect(self._dsn, connect_timeout=5) as conn:
            await conn.execute("SET LOCAL lock_timeout = '3s'")
            row = await (
                await conn.execute(
                    "UPDATE document_knowledge_source SET payload = %s::jsonb, "
                    "revision = revision + 1, claim_id = NULL, lease_until = NULL "
                    "WHERE registry_digest = %s AND source_id = %s "
                    "AND revision = %s AND claim_id = %s AND lease_until > clock_timestamp() "
                    "RETURNING revision",
                    (
                        state.model_dump_json(),
                        registry_digest,
                        source_id,
                        checkpoint.revision,
                        claim,
                    ),
                )
            ).fetchone()
            if row is None:
                raise RuntimeError("source checkpoint lease or revision changed")
            await conn.execute(
                "INSERT INTO document_knowledge_check "
                "(digest, registry_digest, source_id, payload) "
                "VALUES (%s, %s, %s, %s::jsonb) ON CONFLICT DO NOTHING",
                (digest, registry_digest, source_id, receipt.model_dump_json()),
            )

    async def reserve_release(
        self, *, collection_id: str, sequence: int, digest: str, upload_id: UUID, payload: str
    ) -> dict[str, object]:
        """Reserve an immutable sequence; retries reuse the exact original intake binding."""
        async with await psycopg.AsyncConnection.connect(self._dsn, connect_timeout=5) as conn:
            await conn.execute("SET LOCAL lock_timeout = '3s'")
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"cloud-knowledge:{collection_id}",),
            )
            row = await (
                await conn.execute(
                    "SELECT manifest_digest, payload FROM document_knowledge_release "
                    "WHERE collection_id = %s AND sequence = %s",
                    (collection_id, sequence),
                )
            ).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ValueError("knowledge sequence already names different content")
                return dict(row[1])
            latest = await (
                await conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) FROM document_knowledge_release "
                    "WHERE collection_id = %s",
                    (collection_id,),
                )
            ).fetchone()
            if latest is None or sequence <= int(latest[0]):
                raise ValueError("knowledge release replay is not permitted")
            await conn.execute(
                "INSERT INTO document_knowledge_release "
                "(collection_id, sequence, manifest_digest, upload_id, payload) "
                "VALUES (%s, %s, %s, %s, %s::jsonb)",
                (collection_id, sequence, digest, upload_id, payload),
            )
            import json

            return dict(json.loads(payload))

    async def next_sequence(self, collection_id: str) -> int:
        """Propose only; the transactional reservation still arbitrates concurrent writers."""
        async with await psycopg.AsyncConnection.connect(self._dsn, connect_timeout=5) as conn:
            row = await (
                await conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM document_knowledge_release "
                    "WHERE collection_id = %s",
                    (collection_id,),
                )
            ).fetchone()
        if row is None:
            raise RuntimeError("knowledge sequence projection is unavailable")
        return int(row[0])
