"""PostgreSQL adapters for API-owned document records and projections."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol
from uuid import UUID

import psycopg
from fdai_service_contracts import (
    AdapterReadiness,
    DocumentLifecycleConflictError,
    DocumentLifecycleEvent,
    DocumentNotFoundError,
    DocumentVersion,
    KnowledgeChunk,
    UploadSession,
    configured_readiness,
    live_readiness,
    live_unavailable_readiness,
)
from psycopg.rows import dict_row
from pydantic import ValidationError

_LOGGER = logging.getLogger(__name__)


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

    def readiness(self) -> AdapterReadiness:
        """Report validated DSN/timeouts without opening a database connection."""
        return configured_readiness("postgres-document-metadata")

    async def probe_readiness(self) -> AdapterReadiness:
        """Run one bounded read-only database statement."""
        adapter = "postgres-document-metadata"
        try:
            async with asyncio.timeout(min(float(self._config.connect_timeout_s), 5.0)):
                async with await self._connect() as connection:
                    await connection.execute("SELECT 1")
        except TimeoutError:
            return live_unavailable_readiness(adapter, "probe_timeout")
        except Exception as exc:  # noqa: BLE001 - return only the safe exception type
            return live_unavailable_readiness(adapter, f"probe_failed:{type(exc).__name__}")
        return live_readiness(adapter)

    async def create(
        self,
        session: UploadSession,
        version: DocumentVersion,
        *,
        event: DocumentLifecycleEvent | None = None,
    ) -> None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            try:
                await connection.execute(
                    "INSERT INTO document_upload_session "
                    "(upload_id, document_id, version_id, state, revision, payload, "
                    "created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)",
                    (
                        session.upload_id,
                        session.document_id,
                        session.version_id,
                        session.state.value,
                        session.revision,
                        session.model_dump_json(),
                        session.created_at,
                        session.created_at,
                    ),
                )
                await connection.execute(
                    "INSERT INTO document_version "
                    "(document_id, version_id, upload_id, state, active, revision, payload, "
                    "created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)",
                    (
                        version.document_id,
                        version.version_id,
                        version.upload_id,
                        version.state.value,
                        version.active,
                        version.revision,
                        version.model_dump_json(),
                        version.created_at,
                        version.updated_at,
                    ),
                )
                if event is not None:
                    await _enqueue_outbox(connection, event)
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

    async def get_version(self, document_id: UUID, version_id: UUID) -> DocumentVersion:
        row = await self._one(
            "SELECT payload FROM document_version WHERE document_id = %s AND version_id = %s",
            (document_id, version_id),
        )
        if row is None:
            raise DocumentNotFoundError("document version was not found")
        return DocumentVersion.model_validate(_payload(row["payload"]))

    async def transition(
        self,
        session: UploadSession,
        version: DocumentVersion,
        *,
        expected_upload_state: str,
        expected_upload_revision: int,
        expected_version_state: str,
        expected_version_revision: int,
        event: DocumentLifecycleEvent,
    ) -> None:
        """Atomically CAS both lifecycle rows and enqueue one durable event."""
        if session.revision != expected_upload_revision + 1:
            raise ValueError("upload transition revision MUST increment exactly once")
        if version.revision != expected_version_revision + 1:
            raise ValueError("version transition revision MUST increment exactly once")
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            upload_cursor = await connection.execute(
                "UPDATE document_upload_session SET state = %s, revision = %s, "
                "payload = %s::jsonb, updated_at = NOW() WHERE upload_id = %s "
                "AND state = %s AND revision = %s RETURNING upload_id",
                (
                    session.state.value,
                    session.revision,
                    session.model_dump_json(),
                    session.upload_id,
                    expected_upload_state,
                    expected_upload_revision,
                ),
            )
            if await upload_cursor.fetchone() is None:
                raise DocumentLifecycleConflictError("upload lifecycle CAS conflict")
            if version.active:
                await connection.execute(
                    "UPDATE document_version SET active = FALSE, revision = revision + 1, "
                    "payload = jsonb_set(jsonb_set(payload, '{active}', 'false'::jsonb), "
                    "'{revision}', to_jsonb(revision + 1)), "
                    "updated_at = NOW() WHERE document_id = %s AND version_id <> %s AND active",
                    (version.document_id, version.version_id),
                )
            version_cursor = await connection.execute(
                "UPDATE document_version SET state = %s, active = %s, revision = %s, "
                "payload = %s::jsonb, updated_at = %s WHERE document_id = %s "
                "AND version_id = %s AND state = %s AND revision = %s RETURNING version_id",
                (
                    version.state.value,
                    version.active,
                    version.revision,
                    version.model_dump_json(),
                    version.updated_at,
                    version.document_id,
                    version.version_id,
                    expected_version_state,
                    expected_version_revision,
                ),
            )
            if await version_cursor.fetchone() is None:
                raise DocumentLifecycleConflictError("document version lifecycle CAS conflict")
            await _enqueue_outbox(connection, event)

    async def enqueue_event(self, event: DocumentLifecycleEvent) -> None:
        """Persist a replay event when no lifecycle row changes."""
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            await _enqueue_outbox(connection, event)

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
    """Publish committed API outbox rows and retain failures for retry."""

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

    async def drain(self, *, limit: int = 100) -> int:
        """Claim committed rows, publish them, and mark successful deliveries."""
        if limit < 1 or limit > 1000:
            raise ValueError("outbox drain limit MUST be in [1, 1000]")
        rows = await self._claim(limit)
        published = 0
        for row in rows:
            try:
                event = DocumentLifecycleEvent.model_validate(_payload(row["payload"]))
            except (ValidationError, ValueError, RuntimeError):
                logical_topic = str(row["topic"])
                physical_topic = (
                    self._pantheon_topic if logical_topic.startswith("object.") else self._topic
                )
                try:
                    await self._publisher.publish(
                        f"{physical_topic}.dlq",
                        str(row["partition_key"]),
                        {
                            "original_topic": logical_topic,
                            "reason": "invalid_document_api_outbox_event",
                            "outbox_event_id": str(row["event_id"]),
                        },
                    )
                except Exception as exc:  # noqa: BLE001 - preserve row until DLQ succeeds
                    _LOGGER.warning(
                        "document_api_outbox_dead_letter_failed",
                        extra={
                            "event_id": str(row["event_id"]),
                            "exception_type": type(exc).__name__,
                        },
                    )
                    continue
                await self._mark_published(row["event_id"])
                continue
            physical_topic = (
                self._pantheon_topic if event.topic.startswith("object.") else self._topic
            )
            payload = dict(event.payload)
            if physical_topic == self._pantheon_topic:
                payload["_fdai_logical_topic"] = event.topic
            try:
                await self._publisher.publish(physical_topic, event.key, payload)
            except Exception as exc:  # noqa: BLE001 - row remains durable for retry
                _LOGGER.warning(
                    "document_api_outbox_publish_failed",
                    extra={"event_id": str(event.event_id), "exception_type": type(exc).__name__},
                )
                continue
            await self._mark_published(event.event_id)
            published += 1
        return published

    async def _claim(self, limit: int) -> list[dict[str, Any]]:
        async with (
            await psycopg.AsyncConnection.connect(
                self._config.dsn,
                row_factory=dict_row,
                connect_timeout=self._config.connect_timeout_s,
            ) as connection,
            connection.transaction(),
        ):
            rows = await (
                await connection.execute(
                    "SELECT event_id, topic, partition_key, payload FROM document_api_outbox "
                    "WHERE published_at IS NULL "
                    "AND next_attempt_at <= clock_timestamp() ORDER BY created_at, event_id "
                    "FOR UPDATE SKIP LOCKED LIMIT %s",
                    (limit,),
                )
            ).fetchall()
            if rows:
                await connection.execute(
                    "UPDATE document_api_outbox SET attempt_count = attempt_count + 1, "
                    "next_attempt_at = clock_timestamp() + INTERVAL '5 seconds' "
                    "WHERE event_id = ANY(%s)",
                    ([row["event_id"] for row in rows],),
                )
            return rows

    async def _mark_published(self, event_id: UUID) -> None:
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            await connection.execute(
                "UPDATE document_api_outbox SET published_at = clock_timestamp() "
                "WHERE event_id = %s AND published_at IS NULL",
                (event_id,),
            )


class EventPublisher(Protocol):
    """Minimal event publisher shape required by the API activity sink."""

    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> object: ...


async def _enqueue_outbox(
    connection: psycopg.AsyncConnection[Any], event: DocumentLifecycleEvent
) -> None:
    await connection.execute(
        "INSERT INTO document_api_outbox "
        "(event_id, idempotency_key, topic, partition_key, payload, created_at) "
        "VALUES (%s, %s, %s, %s, %s::jsonb, %s) ON CONFLICT (idempotency_key) DO NOTHING",
        (
            event.event_id,
            event.idempotency_key,
            event.topic,
            event.key,
            event.model_dump_json(),
            event.created_at,
        ),
    )


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
