"""Persistent PostgreSQL + pgvector catalog semantic index."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.catalog_search.postgres_generation import (
    PgvectorCatalogGenerationConfig,
    PgvectorCatalogGenerationStore,
)
from fdai.delivery.pgvector.knowledge import _encode_vector
from fdai.shared.providers.catalog_search import (
    CatalogCorpus,
    CatalogGenerationMetadata,
    CatalogSearchDocument,
    CatalogSearchMatch,
    CatalogSearchResult,
    CatalogSemanticIndex,
    Embedder,
)
from fdai.shared.providers.secret_provider import SecretProvider

_IDENTIFIER_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True, slots=True)
class PgvectorCatalogSemanticIndexConfig:
    """Connection secret and bounded hybrid-search tuning."""

    dsn_secret: str
    table: str = "catalog_search_document"
    generation_table: str = "catalog_search_generation"
    generation_document_table: str = "catalog_search_generation_document"
    embedding_dim: int = 384
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10
    ivfflat_probes: int = 10

    def __post_init__(self) -> None:
        if not self.dsn_secret:
            raise ValueError("dsn_secret MUST be non-empty")
        for table in (self.table, self.generation_table, self.generation_document_table):
            if not _IDENTIFIER_RE.fullmatch(table):
                raise ValueError("table MUST be a plain ASCII SQL identifier")
        if self.embedding_dim < 1:
            raise ValueError("embedding_dim MUST be >= 1")
        if self.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        if self.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")
        if self.ivfflat_probes < 1:
            raise ValueError("ivfflat_probes MUST be >= 1")


class PgvectorCatalogSemanticIndex(CatalogSemanticIndex):
    """Persistent hybrid index over grounded Rule and typed-neighbor text."""

    def __init__(
        self,
        *,
        config: PgvectorCatalogSemanticIndexConfig,
        embedder: Embedder,
        secrets: SecretProvider,
    ) -> None:
        self._config = config
        self._embedder = embedder
        self._secrets = secrets
        self._generations = PgvectorCatalogGenerationStore(
            config=PgvectorCatalogGenerationConfig(
                dsn_secret=config.dsn_secret,
                generation_table=config.generation_table,
                document_table=config.generation_document_table,
                embedding_dim=config.embedding_dim,
                statement_timeout_ms=config.statement_timeout_ms,
                connect_timeout_s=config.connect_timeout_s,
                ivfflat_probes=config.ivfflat_probes,
            ),
            embedder=embedder,
            secrets=secrets,
        )

    async def upsert(self, documents: Sequence[CatalogSearchDocument]) -> int:
        if not documents:
            return 0
        rows = []
        for document in documents:
            stored = document
            if not stored.embedding:
                stored = replace(
                    stored,
                    embedding=tuple(await self._embedder.embed(stored.text)),
                )
            literal = _encode_vector(stored.embedding, dim=self._config.embedding_dim)
            rows.append((stored, literal, _content_hash(stored)))

        dsn = await self._secrets.get(self._config.dsn_secret)
        table = self._config.table
        changed = 0
        async with await psycopg.AsyncConnection.connect(
            dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await self._set_session_knobs(connection)
                cursor = await connection.execute(
                    f"SELECT rule_id, content_hash FROM {table} WHERE rule_id = ANY(%s)",  # noqa: S608
                    ([document.rule_id for document, _, _ in rows],),
                )
                previous = {
                    str(row["rule_id"]): str(row["content_hash"]) for row in await cursor.fetchall()
                }
                for document, literal, content_hash in rows:
                    if previous.get(document.rule_id) == content_hash:
                        continue
                    await connection.execute(
                        f"""
                        INSERT INTO {table} (
                            rule_id, text, neighbor_ids, search_vector,
                            embedding, content_hash, updated_at
                        ) VALUES (
                            %s, %s, %s, to_tsvector('simple', %s),
                            %s::vector, %s, NOW()
                        )
                        ON CONFLICT (rule_id) DO UPDATE SET
                            text = EXCLUDED.text,
                            neighbor_ids = EXCLUDED.neighbor_ids,
                            search_vector = EXCLUDED.search_vector,
                            embedding = EXCLUDED.embedding,
                            content_hash = EXCLUDED.content_hash,
                            updated_at = NOW()
                        """,  # noqa: S608
                        (
                            document.rule_id,
                            document.text,
                            list(document.neighbor_ids),
                            f"{document.rule_id}\n{document.text}",
                            literal,
                            content_hash,
                        ),
                    )
                    changed += 1
        return changed

    async def synchronize(self, documents: Sequence[CatalogSearchDocument]) -> int:
        changed = await self.upsert(documents)
        expected_ids = [document.rule_id for document in documents]
        dsn = await self._secrets.get(self._config.dsn_secret)
        table = self._config.table
        async with await psycopg.AsyncConnection.connect(
            dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await self._set_session_knobs(connection)
                if expected_ids:
                    cursor = await connection.execute(
                        f"DELETE FROM {table} WHERE NOT (rule_id = ANY(%s))",  # noqa: S608
                        (expected_ids,),
                    )
                else:
                    cursor = await connection.execute(f"DELETE FROM {table}")  # noqa: S608
                removed = cursor.rowcount or 0
        return changed + removed

    async def stage_generation(
        self,
        metadata: CatalogGenerationMetadata,
        documents: Sequence[CatalogSearchDocument],
    ) -> int:
        return await self._generations.stage_generation(metadata, documents)

    async def activate_generation(
        self,
        generation_id: str,
        *,
        expected_generation_digest: str,
        activated_at: datetime,
    ) -> CatalogGenerationMetadata:
        return await self._generations.activate_generation(
            generation_id,
            expected_generation_digest=expected_generation_digest,
            activated_at=activated_at,
        )

    async def active_generation(
        self, corpus: CatalogCorpus = "active"
    ) -> CatalogGenerationMetadata | None:
        return await self._generations.active_generation(corpus)

    async def search(
        self,
        query: str,
        *,
        k: int = 20,
        corpus: CatalogCorpus = "active",
        expected_catalog_digest: str | None = None,
    ) -> Sequence[CatalogSearchResult]:
        normalized_query = query.strip()
        if not normalized_query or k <= 0:
            return ()
        generation = await self.active_generation(corpus)
        if generation is not None or expected_catalog_digest is not None:
            return await self._generations.search(
                normalized_query,
                k=k,
                corpus=corpus,
                expected_catalog_digest=expected_catalog_digest,
            )
        query_vector = await self._embedder.embed(normalized_query)
        literal = _encode_vector(query_vector, dim=self._config.embedding_dim)
        dsn = await self._secrets.get(self._config.dsn_secret)
        table = self._config.table
        async with await psycopg.AsyncConnection.connect(
            dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await self._set_session_knobs(connection)
                cursor = await connection.execute(
                    _search_sql(table),
                    (normalized_query, normalized_query, literal, normalized_query, int(k)),
                )
                rows = await cursor.fetchall()
        return tuple(_row_to_result(row) for row in rows)

    async def _set_session_knobs(self, connection: psycopg.AsyncConnection[Any]) -> None:
        timeout_ms = int(self._config.statement_timeout_ms)
        probes = int(self._config.ivfflat_probes)
        await connection.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
        await connection.execute(f"SET LOCAL ivfflat.probes = {probes}")


def _content_hash(document: CatalogSearchDocument) -> str:
    payload = {
        "rule_id": document.rule_id,
        "text": document.text,
        "neighbor_ids": document.neighbor_ids,
        "embedding": document.embedding,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _search_sql(table: str) -> str:
    return f"""
        WITH scored AS (
            SELECT document.rule_id,
                   lower(document.rule_id) = lower(%s) AS exact_id,
                   ts_rank_cd(
                       document.search_vector,
                       plainto_tsquery('simple', %s)
                   ) AS lexical_score,
                   1.0 - (document.embedding <=> %s::vector) AS semantic_score,
                   COALESCE(neighbor.score, 0.0) AS neighbor_score
              FROM {table} AS document
              LEFT JOIN LATERAL (
                  SELECT MAX(similarity(neighbor_id, %s)) AS score
                    FROM unnest(document.neighbor_ids) AS neighbor_id
              ) AS neighbor ON TRUE
        ), ranked AS (
            SELECT scored.*,
                   row_number() OVER (
                       ORDER BY lexical_score DESC, rule_id ASC
                   ) AS lexical_rank,
                   row_number() OVER (
                       ORDER BY semantic_score DESC, rule_id ASC
                   ) AS semantic_rank
              FROM scored
        ), fused AS (
            SELECT ranked.*,
                   1.0 / (60.0 + lexical_rank)
                   + 1.0 / (60.0 + semantic_rank) AS fusion_score
              FROM ranked
        )
        SELECT rule_id,
               exact_id,
               lexical_score,
               semantic_score,
               neighbor_score,
               fusion_score,
               exact_id::int + neighbor_score + fusion_score
                   + lexical_score + semantic_score AS total_score
          FROM fused
         WHERE exact_id
            OR lexical_score > 0
            OR semantic_score >= 0.35
                OR neighbor_score >= 0.3
         ORDER BY exact_id DESC,
                  neighbor_score DESC,
                  fusion_score DESC,
                  lexical_score DESC,
                  semantic_score DESC,
                  rule_id ASC
         LIMIT %s
        """  # noqa: S608


def _row_to_result(row: Mapping[str, Any]) -> CatalogSearchResult:
    match: CatalogSearchMatch = "exact_id" if bool(row["exact_id"]) else "hybrid"
    return CatalogSearchResult(
        rule_id=str(row["rule_id"]),
        score=float(row["total_score"]),
        match=match,
        components={
            "exact": float(bool(row["exact_id"])),
            "neighbor": float(row["neighbor_score"]),
            "reciprocal_rank": float(row["fusion_score"]),
            "lexical": float(row["lexical_score"]),
            "semantic": float(row["semantic_score"]),
        },
    )


__all__ = ["PgvectorCatalogSemanticIndex", "PgvectorCatalogSemanticIndexConfig"]
