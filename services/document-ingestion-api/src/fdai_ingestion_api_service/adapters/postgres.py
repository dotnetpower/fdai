"""PostgreSQL adapters for API-owned document records and projections."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
from fdai_service_contracts import (
    AUDIT_APPEND_LOCK_KEY,
    AUDIT_GENESIS_HASH,
    DocumentNotFoundError,
    DocumentVersion,
    KnowledgeChunk,
    UploadSession,
    canonical_audit_entry,
    next_audit_hash,
)
from psycopg.rows import dict_row


@dataclass(frozen=True, slots=True)
class PostgresApiConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("Postgres API DSN MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("Postgres API timeouts MUST be positive")


class PostgresDocumentMetadataStore:
    """Persist upload and version transitions under the API database role."""

    def __init__(self, *, config: PostgresApiConfig) -> None:
        self._config: Final = config

    async def create(self, session: UploadSession, version: DocumentVersion) -> None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            try:
                await connection.execute(
                    "INSERT INTO document_upload_session "
                    "(upload_id, document_id, version_id, state, payload, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)",
                    (
                        session.upload_id,
                        session.document_id,
                        session.version_id,
                        session.state.value,
                        session.model_dump_json(),
                        session.created_at,
                        session.created_at,
                    ),
                )
                await connection.execute(
                    "INSERT INTO document_version "
                    "(document_id, version_id, upload_id, state, active, payload, "
                    "created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)",
                    (
                        version.document_id,
                        version.version_id,
                        version.upload_id,
                        version.state.value,
                        version.active,
                        version.model_dump_json(),
                        version.created_at,
                        version.updated_at,
                    ),
                )
            except psycopg.errors.UniqueViolation as exc:
                raise ValueError("document upload or version already exists") from exc

    async def get_upload(self, upload_id: UUID) -> UploadSession:
        row = await self._one(
            "SELECT payload FROM document_upload_session WHERE upload_id = %s",
            (upload_id,),
        )
        if row is None:
            raise DocumentNotFoundError("upload was not found")
        return UploadSession.model_validate(_payload(row["payload"]))

    async def save_upload(self, session: UploadSession) -> None:
        await self._update(
            "UPDATE document_upload_session SET state = %s, payload = %s::jsonb, "
            "updated_at = NOW() WHERE upload_id = %s RETURNING upload_id",
            (session.state.value, session.model_dump_json(), session.upload_id),
            "upload was not found",
        )

    async def get_version(self, document_id: UUID, version_id: UUID) -> DocumentVersion:
        row = await self._one(
            "SELECT payload FROM document_version WHERE document_id = %s AND version_id = %s",
            (document_id, version_id),
        )
        if row is None:
            raise DocumentNotFoundError("document version was not found")
        return DocumentVersion.model_validate(_payload(row["payload"]))

    async def save_version(self, version: DocumentVersion) -> None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            if version.active:
                await connection.execute(
                    "UPDATE document_version SET active = FALSE, "
                    "payload = jsonb_set(payload, '{active}', 'false'::jsonb), updated_at = NOW() "
                    "WHERE document_id = %s AND version_id <> %s AND active",
                    (version.document_id, version.version_id),
                )
            cursor = await connection.execute(
                "UPDATE document_version SET state = %s, active = %s, payload = %s::jsonb, "
                "updated_at = %s WHERE document_id = %s AND version_id = %s RETURNING version_id",
                (
                    version.state.value,
                    version.active,
                    version.model_dump_json(),
                    version.updated_at,
                    version.document_id,
                    version.version_id,
                ),
            )
            if await cursor.fetchone() is None:
                raise DocumentNotFoundError("document version was not found")

    async def list_versions(self, document_id: UUID) -> tuple[DocumentVersion, ...]:
        rows = await self._many(
            "SELECT payload FROM document_version WHERE document_id = %s "
            "ORDER BY created_at ASC, version_id ASC",
            (document_id,),
        )
        if not rows:
            raise DocumentNotFoundError("document was not found")
        return tuple(DocumentVersion.model_validate(_payload(row["payload"])) for row in rows)

    async def list_uploads_by_state(self, state: str, *, limit: int) -> tuple[UploadSession, ...]:
        if limit < 1 or limit > 1000:
            raise ValueError("document upload state limit MUST be in [1, 1000]")
        rows = await self._many(
            "SELECT payload FROM document_upload_session WHERE state = %s "
            "ORDER BY created_at ASC, upload_id ASC LIMIT %s",
            (state, limit),
        )
        return tuple(UploadSession.model_validate(_payload(row["payload"])) for row in rows)

    async def _one(self, query: str, params: tuple[object, ...]) -> dict[str, Any] | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            return await (await connection.execute(query, params)).fetchone()

    async def _many(self, query: str, params: tuple[object, ...]) -> list[dict[str, Any]]:
        async with await self._connect() as connection:
            await self._timeout(connection)
            return await (await connection.execute(query, params)).fetchall()

    async def _update(self, query: str, params: tuple[object, ...], not_found: str) -> None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            if await (await connection.execute(query, params)).fetchone() is None:
                raise DocumentNotFoundError(not_found)

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            f"SET LOCAL statement_timeout = {int(self._config.statement_timeout_ms)}"
        )


class PostgresDocumentActivitySink:
    """Append hash-chained lifecycle audit records before event publication."""

    def __init__(
        self,
        *,
        config: PostgresApiConfig,
        publisher: EventPublisher,
        topic: str,
        pantheon_topic: str,
    ) -> None:
        self._config = config
        self._publisher = publisher
        self._topic = topic
        self._pantheon_topic = pantheon_topic

    async def audit(self, record: Mapping[str, object]) -> None:
        payload = dict(record)
        canonical = canonical_audit_entry(payload)
        async with (
            await psycopg.AsyncConnection.connect(
                self._config.dsn,
                connect_timeout=self._config.connect_timeout_s,
            ) as connection,
            connection.transaction(),
        ):
            await connection.execute("SELECT pg_advisory_xact_lock(%s)", (AUDIT_APPEND_LOCK_KEY,))
            row = await (
                await connection.execute(
                    "SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1"
                )
            ).fetchone()
            previous = str(row[0]) if row is not None else AUDIT_GENESIS_HASH
            entry_hash = next_audit_hash(previous, payload)
            identity = str(payload.get("idempotency_key") or canonical)
            event_id = str(uuid5(NAMESPACE_URL, f"fdai.audit://{identity}"))
            await connection.execute(
                "INSERT INTO audit_log (event_id, correlation_id, actor, action_kind, mode, "
                "entry, previous_hash, entry_hash) VALUES "
                "(%s::uuid, %s, %s, %s, 'shadow', %s::jsonb, %s, %s)",
                (
                    event_id,
                    payload.get("correlation_id"),
                    str(payload.get("actor_id") or "fdai.system"),
                    str(payload.get("action") or "document.activity"),
                    canonical,
                    previous,
                    entry_hash,
                ),
            )

    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> None:
        event = dict(payload)
        event["event_type"] = topic
        try:
            await self._publisher.publish(self._topic, key, event)
        except Exception:
            return
        if topic in {"document.received", "document.inspected"}:
            correlation_id = str(payload.get("upload_id") or key)
            version_id = str(payload.get("version_id") or "")
            await self._publisher.publish(
                self._pantheon_topic,
                key,
                {
                    "_fdai_logical_topic": "object.event",
                    "producer_principal": "Huginn",
                    "kind": "document_ingestion",
                    "action": topic,
                    "event_type": topic,
                    "correlation_id": correlation_id,
                    "idempotency_key": f"{topic}:{version_id or correlation_id}",
                    "resource_id": key,
                    "resource_type": "document",
                    "document_id": key,
                    "record": dict(payload),
                },
            )


class EventPublisher(Protocol):
    """Minimal event publisher shape required by the API activity sink."""

    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> object: ...


class PostgresDocumentSearch:
    """Return bounded authorized document chunks using pgvector cosine ranking."""

    def __init__(
        self,
        *,
        config: PostgresApiConfig,
        embedder: EmbeddingProvider,
        dimension: int,
    ) -> None:
        self._config = config
        self._embedder = embedder
        self._dimension = dimension

    async def search(
        self,
        query: str,
        *,
        collection_id: str,
        allowed_access_refs: frozenset[str],
        k: int = 5,
    ) -> Sequence[KnowledgeChunk]:
        if not query or not allowed_access_refs or k < 1 or k > 20:
            return ()
        vector = _vector(await self._embedder.embed(query), self._dimension)
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            rows = await (
                await connection.execute(
                    "SELECT doc_id, chunk_id, text, source_ref, metadata, "
                    "1.0 - (embedding <=> %s::vector) AS score "
                    "FROM knowledge_chunk WHERE metadata->>'governed_document' = 'true' "
                    "AND metadata->>'collection_id' = %s "
                    "AND metadata->>'access_descriptor_ref' = ANY(%s) "
                    "ORDER BY embedding <=> %s::vector ASC LIMIT %s",
                    (vector, collection_id, sorted(allowed_access_refs), vector, k),
                )
            ).fetchall()
        return tuple(
            KnowledgeChunk(
                doc_id=str(row["doc_id"]),
                chunk_id=str(row["chunk_id"]),
                text=str(row["text"]),
                source_ref=str(row["source_ref"]),
                metadata=_payload(row["metadata"]),
                score=float(row["score"]),
            )
            for row in rows
        )


class EmbeddingProvider(Protocol):
    async def embed(self, text: str) -> Sequence[float]: ...


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    raise RuntimeError("document metadata payload is not a JSON object")


def _vector(values: Sequence[float], dimension: int) -> str:
    if len(values) != dimension:
        raise ValueError("embedding vector dimension mismatch")
    return "[" + ",".join(format(float(value), ".12g") for value in values) + "]"
