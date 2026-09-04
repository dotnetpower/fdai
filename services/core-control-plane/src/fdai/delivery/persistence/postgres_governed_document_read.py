"""Read-only PostgreSQL adapters for governed RCA document evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import psycopg
from psycopg import IsolationLevel
from psycopg.rows import dict_row

from fdai.shared.contracts import DocumentVersion
from fdai.shared.providers.document_ingestion import (
    DocumentAccessDeniedError,
    DocumentNotFoundError,
)
from fdai.shared.providers.knowledge import KnowledgeChunk

_SEARCH_SQL = """
WITH inputs AS (
    SELECT websearch_to_tsquery('simple', %s) AS query
),
authorized AS MATERIALIZED (
    SELECT chunk.doc_id,
           chunk.chunk_id,
           chunk.text,
           chunk.source_ref,
           chunk.metadata,
           ts_rank_cd(to_tsvector('simple', chunk.text), inputs.query) AS score
      FROM knowledge_chunk AS chunk
      CROSS JOIN inputs
     WHERE chunk.metadata->>'governed_document' = 'true'
       AND chunk.metadata->>'collection_id' = %s
       AND chunk.metadata->>'access_descriptor_ref' = ANY(%s)
       AND to_tsvector('simple', chunk.text) @@ inputs.query
)
SELECT doc_id, chunk_id, text, source_ref, metadata, score
  FROM authorized
 ORDER BY score DESC, chunk_id ASC
 LIMIT %s
"""


@dataclass(frozen=True, slots=True)
class PostgresGovernedDocumentReadConfig:
    """Connection and statement bounds for governed read-only queries."""

    dsn: str
    statement_timeout_ms: int = 10_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn.strip():
            raise ValueError("governed document read DSN MUST be non-empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("governed document read timeouts MUST be positive")


class PostgresGovernedDocumentReadStore:
    """Search and revalidate governed document revisions without write methods."""

    def __init__(self, *, config: PostgresGovernedDocumentReadConfig) -> None:
        self._config = config

    async def search(
        self,
        query: str,
        *,
        collection_id: str,
        allowed_access_refs: frozenset[str],
        k: int = 5,
    ) -> Sequence[KnowledgeChunk]:
        """Return authorized lexical candidates in deterministic rank order."""

        if (
            not query.strip()
            or len(query) > 20_000
            or not collection_id.strip()
            or len(collection_id) > 256
            or not allowed_access_refs
            or any(not value.strip() or len(value) > 512 for value in allowed_access_refs)
            or not 1 <= k <= 20
        ):
            raise ValueError("governed document search inputs are invalid")
        async with await self._connect() as connection:
            await connection.set_isolation_level(IsolationLevel.REPEATABLE_READ)
            await connection.set_read_only(True)
            await self._set_timeout(connection)
            cursor = await connection.execute(
                _SEARCH_SQL,
                (query, collection_id, sorted(allowed_access_refs), k),
            )
            rows = await cursor.fetchall()
        return tuple(
            KnowledgeChunk(
                doc_id=str(row["doc_id"]),
                chunk_id=str(row["chunk_id"]),
                text=str(row["text"]),
                source_ref=str(row["source_ref"]),
                metadata=_json_object(row["metadata"]),
                score=float(row["score"]),
            )
            for row in rows
        )

    async def get_version(self, document_id: UUID, version_id: UUID) -> DocumentVersion:
        """Return one immutable version payload or a uniform not-found result."""

        async with await self._connect() as connection:
            await connection.set_isolation_level(IsolationLevel.REPEATABLE_READ)
            await connection.set_read_only(True)
            await self._set_timeout(connection)
            cursor = await connection.execute(
                "SELECT payload FROM document_version WHERE document_id=%s AND version_id=%s",
                (document_id, version_id),
            )
            row = await cursor.fetchone()
        if row is None:
            raise DocumentNotFoundError("document version was not found")
        return DocumentVersion.model_validate(_json_object(row["payload"]))

    async def authorize_read(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        version: DocumentVersion,
    ) -> None:
        """Require uploader identity or an exact document reader group."""

        allowed_groups = frozenset(version.access.reader_groups)
        if actor_id != version.uploader_id and not actor_groups.intersection(allowed_groups):
            raise DocumentAccessDeniedError("governed document access is denied")

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
            options="",
        )

    async def _set_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _json_object(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise RuntimeError("governed document payload is not valid JSON") from exc
        if isinstance(parsed, Mapping):
            return dict(parsed)
    raise RuntimeError("governed document payload is not a JSON object")


__all__ = [
    "PostgresGovernedDocumentReadConfig",
    "PostgresGovernedDocumentReadStore",
]
