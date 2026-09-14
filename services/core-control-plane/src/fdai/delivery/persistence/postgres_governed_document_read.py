"""Read-only PostgreSQL adapters for governed RCA document evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import psycopg
from fdai_service_contracts.cloud_knowledge import Applicability
from fdai_service_contracts.document import (
    DocumentDisposition,
    DocumentIndexState,
    DocumentRetentionState,
)
from fdai_service_contracts.document import (
    DocumentVersion as ServiceDocumentVersion,
)
from psycopg import IsolationLevel
from psycopg.rows import dict_row

from fdai.shared.contracts import DocumentVersion
from fdai.shared.providers.document_ingestion import (
    DocumentAccessDeniedError,
    DocumentNotFoundError,
    GovernedDocumentSearchResult,
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
       AND chunk.metadata->>'retention_state' = 'live'
      AND EXISTS (
         SELECT 1 FROM document_version AS version
          WHERE version.document_id::text = chunk.metadata->>'document_id'
            AND version.version_id::text = chunk.metadata->>'version_id'
            AND version.active AND version.payload->>'available' = 'true'
            AND version.state IN ('ready', 'ready_with_warnings')
      )
      AND (chunk.metadata->>'cloud_admission_expires_at' IS NULL
          OR (chunk.metadata->>'cloud_admission_expires_at')::timestamptz > NOW())
       AND to_tsvector('simple', chunk.text) @@ inputs.query
)
SELECT doc_id, chunk_id, text, source_ref, metadata, score
  FROM authorized
 ORDER BY score DESC, chunk_id ASC
 LIMIT %s
"""

_EXACT_SEARCH_SQL = """
WITH inputs AS (
        SELECT websearch_to_tsquery('simple', %s) AS query
),
exact_refs AS (
        SELECT document_id, version_id
            FROM jsonb_to_recordset(%s::jsonb) AS ref(document_id text, version_id text)
),
authorized AS MATERIALIZED (
        SELECT chunk.doc_id,
                     chunk.chunk_id,
                     chunk.text,
                     chunk.source_ref,
                     chunk.metadata,
                     ts_rank_cd(to_tsvector('simple', chunk.text), inputs.query) AS score
            FROM knowledge_chunk AS chunk
            JOIN exact_refs AS ref
                ON chunk.metadata->>'document_id' = ref.document_id
             AND chunk.metadata->>'version_id' = ref.version_id
            CROSS JOIN inputs
         WHERE chunk.metadata->>'governed_document' = 'true'
             AND (
                    (
                        %s = 'channel_attachment'
                        AND chunk.metadata->>'disposition' = 'session_ephemeral'
                        AND chunk.metadata->>'scope_kind' = 'conversation'
                        AND chunk.metadata->>'scope_ref' = %s
                    )
                    OR
                    (
                        %s = 'web_reference'
                        AND chunk.metadata->>'disposition' = 'governed_knowledge'
                        AND chunk.metadata->>'scope_kind' = 'collection'
                        AND chunk.metadata->>'scope_ref'
                            = chunk.metadata->>'collection_id'
                    )
               )
             AND chunk.metadata->>'retention_state' = 'live'
             AND to_tsvector('simple', chunk.text) @@ inputs.query
)
SELECT doc_id, chunk_id, text, source_ref, metadata, score
    FROM authorized
 ORDER BY score DESC, doc_id ASC, chunk_id ASC
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
        hits, _snapshot = await self._search_snapshot(
            query,
            collection_id=collection_id,
            allowed_access_refs=allowed_access_refs,
            k=k,
        )
        return hits

    async def search_governed(
        self,
        query: str,
        *,
        collection_id: str,
        allowed_access_refs: frozenset[str],
        k: int = 5,
    ) -> GovernedDocumentSearchResult:
        """Return a provider snapshot without claiming unproven index completeness."""

        hits, snapshot = await self._search_snapshot(
            query,
            collection_id=collection_id,
            allowed_access_refs=allowed_access_refs,
            k=k,
        )
        generation = hashlib.sha256(snapshot.encode()).hexdigest()
        return GovernedDocumentSearchResult(
            hits=hits,
            index_generation=f"postgres-document-index:sha256:{generation}",
            complete=False,
            limitation="index_completeness_unverified",
        )

    async def search_applicable_governed(
        self,
        query: str,
        *,
        collection_id: str,
        allowed_access_refs: frozenset[str],
        target: Applicability,
        k: int = 5,
    ) -> GovernedDocumentSearchResult:
        """Restrict cloud target identity and conditions in the authorized relation before rank."""
        hits, snapshot = await self._search_snapshot(
            query,
            collection_id=collection_id,
            allowed_access_refs=allowed_access_refs,
            k=k,
            target=target,
        )
        return GovernedDocumentSearchResult(
            hits=hits,
            index_generation="postgres-document-index:sha256:"
            + hashlib.sha256(snapshot.encode()).hexdigest(),
            complete=False,
            limitation="index_completeness_unverified",
        )

    async def search_governed_exact(
        self,
        query: str,
        *,
        exact_refs: tuple[tuple[UUID, UUID], ...],
        context_source: str,
        conversation_ref: str,
        k: int = 5,
    ) -> GovernedDocumentSearchResult:
        """Search only exact, source-scoped revisions from an active index."""

        hits, snapshot = await self._search_exact_snapshot(
            query,
            exact_refs=exact_refs,
            context_source=context_source,
            conversation_ref=conversation_ref,
            k=k,
        )
        identity = json.dumps(
            {
                "snapshot": snapshot,
                "context_source": context_source,
                "conversation_ref": conversation_ref,
                "exact_refs": [
                    {"document_id": str(document_id), "version_id": str(version_id)}
                    for document_id, version_id in exact_refs
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        generation = hashlib.sha256(identity.encode()).hexdigest()
        return GovernedDocumentSearchResult(
            hits=hits,
            index_generation=f"postgres-document-index:sha256:{generation}",
            complete=True,
            limitation=None,
        )

    async def search_applicable_governed_exact(
        self,
        query: str,
        *,
        exact_refs: tuple[tuple[UUID, UUID], ...],
        context_source: str,
        conversation_ref: str,
        target: Applicability,
        k: int = 5,
    ) -> GovernedDocumentSearchResult:
        """Intersect authorized exact revisions with provider conditions before rank."""
        hits, snapshot = await self._search_exact_snapshot(
            query,
            exact_refs=exact_refs,
            context_source=context_source,
            conversation_ref=conversation_ref,
            k=k,
            target=target,
        )
        return GovernedDocumentSearchResult(
            hits=hits,
            index_generation="postgres-document-index:sha256:"
            + hashlib.sha256(snapshot.encode()).hexdigest(),
            complete=True,
            limitation=None,
        )

    async def _search_snapshot(
        self,
        query: str,
        *,
        collection_id: str,
        allowed_access_refs: frozenset[str],
        k: int,
        target: Applicability | None = None,
    ) -> tuple[tuple[KnowledgeChunk, ...], str]:
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
            snapshot_row = await (
                await connection.execute("SELECT txid_current_snapshot()::text AS snapshot")
            ).fetchone()
            if snapshot_row is None or not isinstance(snapshot_row.get("snapshot"), str):
                raise RuntimeError("governed document index snapshot is unavailable")
            sql = _SEARCH_SQL
            parameters: tuple[object, ...] = (query, collection_id, sorted(allowed_access_refs), k)
            if target is not None:
                applicability_sql = "(chunk.metadata->>'cloud_source')::jsonb->'applicability'"
                unknown_constraints = "".join(
                    f"AND {applicability_sql}->'{field}' = '[]'::jsonb "
                    for field in ("skus", "api_versions", "regions", "deployment_modes")
                    if not getattr(target, field)
                )
                sql = sql.replace(
                    "AND to_tsvector('simple', chunk.text) @@ inputs.query",
                    f"AND {applicability_sql} @> %s::jsonb "
                    + unknown_constraints
                    + "AND to_tsvector('simple', chunk.text) @@ inputs.query",
                )
                parameters = (
                    query,
                    collection_id,
                    sorted(allowed_access_refs),
                    target.model_dump_json(),
                    k,
                )
            cursor = await connection.execute(sql, parameters)
            rows = await cursor.fetchall()
        hits = tuple(
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
        return hits, snapshot_row["snapshot"]

    async def _search_exact_snapshot(
        self,
        query: str,
        *,
        exact_refs: tuple[tuple[UUID, UUID], ...],
        context_source: str,
        conversation_ref: str,
        k: int,
        target: Applicability | None = None,
    ) -> tuple[tuple[KnowledgeChunk, ...], str]:
        if (
            not query.strip()
            or len(query) > 20_000
            or not 1 <= len(exact_refs) <= 8
            or len(exact_refs) != len(set(exact_refs))
            or context_source not in {"channel_attachment", "web_reference"}
            or not conversation_ref.strip()
            or len(conversation_ref) > 256
            or not 1 <= k <= 20
        ):
            raise ValueError("exact governed document search inputs are invalid")
        exact_payload = json.dumps(
            [
                {"document_id": str(document_id), "version_id": str(version_id)}
                for document_id, version_id in exact_refs
            ],
            sort_keys=True,
            separators=(",", ":"),
        )
        async with await self._connect() as connection:
            await connection.set_isolation_level(IsolationLevel.REPEATABLE_READ)
            await connection.set_read_only(True)
            await self._set_timeout(connection)
            snapshot_row = await (
                await connection.execute("SELECT txid_current_snapshot()::text AS snapshot")
            ).fetchone()
            if snapshot_row is None or not isinstance(snapshot_row.get("snapshot"), str):
                raise RuntimeError("governed document index snapshot is unavailable")
            sql = _EXACT_SEARCH_SQL
            parameters: tuple[object, ...] = (
                query,
                exact_payload,
                context_source,
                conversation_ref,
                context_source,
                k,
            )
            if target is not None:
                applicability_sql = "(chunk.metadata->>'cloud_source')::jsonb->'applicability'"
                unknown_constraints = "".join(
                    f"AND {applicability_sql}->'{field}' = '[]'::jsonb "
                    for field in ("skus", "api_versions", "regions", "deployment_modes")
                    if not getattr(target, field)
                )
                sql = sql.replace(
                    "AND to_tsvector('simple', chunk.text) @@ inputs.query",
                    f"AND {applicability_sql} @> %s::jsonb "
                    + unknown_constraints
                    + "AND (chunk.metadata->>'cloud_admission_expires_at')::timestamptz > NOW() "
                    + "AND to_tsvector('simple', chunk.text) @@ inputs.query",
                )
                parameters = (*parameters[:-1], target.model_dump_json(), k)
            cursor = await connection.execute(sql, parameters)
            rows = await cursor.fetchall()
        hits = tuple(
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
        return hits, snapshot_row["snapshot"]

    async def get_version(self, document_id: UUID, version_id: UUID) -> DocumentVersion:
        """Return one immutable version payload or a uniform not-found result."""

        current = await self.get_current_version(document_id, version_id)
        return _project_governed_document_version(current)

    async def get_current_version(
        self,
        document_id: UUID,
        version_id: UUID,
    ) -> ServiceDocumentVersion:
        """Return the full current service contract for exact-scope reauthorization."""

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
        return ServiceDocumentVersion.model_validate(_json_object(row["payload"]))

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


def _document_version(value: object) -> DocumentVersion:
    """Decode the current service contract, then project the legacy Core view."""

    current = ServiceDocumentVersion.model_validate(_json_object(value))
    return _project_governed_document_version(current)


def _project_governed_document_version(
    current: ServiceDocumentVersion,
) -> DocumentVersion:
    """Project only active governed knowledge into the legacy Core contract."""

    if (
        current.disposition is not DocumentDisposition.GOVERNED_KNOWLEDGE
        or current.index_state is not DocumentIndexState.ACTIVE
        or current.retention_state is not DocumentRetentionState.LIVE
    ):
        raise DocumentNotFoundError("document version is not active governed knowledge")
    legacy_fields = set(DocumentVersion.model_fields)
    return DocumentVersion.model_validate(current.model_dump(mode="json", include=legacy_fields))


__all__ = [
    "PostgresGovernedDocumentReadConfig",
    "PostgresGovernedDocumentReadStore",
]
