"""Atomic PostgreSQL generations for the catalog semantic index."""

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

from fdai.delivery.pgvector.knowledge import _encode_vector
from fdai.shared.ontology.compatibility import OntologyGenerationCompatibilityReceipt
from fdai.shared.providers.catalog_search import (
    CatalogCorpus,
    CatalogGenerationMetadata,
    CatalogGenerationRollbackReceipt,
    CatalogGenerationStaleError,
    CatalogSearchDocument,
    CatalogSearchMatch,
    CatalogSearchResult,
    Embedder,
)
from fdai.shared.providers.secret_provider import SecretProvider

from .generation_rollback import plan_catalog_generation_rollback

_IDENTIFIER_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True, slots=True)
class PgvectorCatalogGenerationConfig:
    """Persistent generation tables and bounded query tuning."""

    dsn_secret: str
    generation_table: str = "catalog_search_generation"
    document_table: str = "catalog_search_generation_document"
    embedding_dim: int = 384
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10
    ivfflat_probes: int = 10

    def __post_init__(self) -> None:
        if not self.dsn_secret:
            raise ValueError("dsn_secret MUST be non-empty")
        for value in (self.generation_table, self.document_table):
            if not _IDENTIFIER_RE.fullmatch(value):
                raise ValueError("generation tables MUST be plain ASCII SQL identifiers")
        if (
            min(
                self.embedding_dim,
                self.statement_timeout_ms,
                self.connect_timeout_s,
                self.ivfflat_probes,
            )
            < 1
        ):
            raise ValueError("generation numeric configuration MUST be positive")


class PgvectorCatalogGenerationStore:
    """Stage complete generations and expose only one validated corpus pointer."""

    def __init__(
        self,
        *,
        config: PgvectorCatalogGenerationConfig,
        embedder: Embedder,
        secrets: SecretProvider,
    ) -> None:
        self._config = config
        self._embedder = embedder
        self._secrets = secrets

    async def stage_generation(
        self,
        metadata: CatalogGenerationMetadata,
        documents: Sequence[CatalogSearchDocument],
    ) -> int:
        """Persist one complete inactive generation in a single transaction."""

        if metadata.state != "staged":
            raise ValueError("only staged catalog generations can be written")
        if metadata.embedding_dimension != self._config.embedding_dim:
            raise ValueError("catalog generation embedding dimension mismatch")
        if not documents or len({item.rule_id for item in documents}) != len(documents):
            raise ValueError("catalog generation documents MUST be non-empty with unique Rule ids")
        rows = []
        for document in documents:
            stored = replace(
                document,
                corpus=metadata.corpus,
                generation_id=metadata.generation_id,
            )
            if not stored.embedding:
                stored = replace(stored, embedding=tuple(await self._embedder.embed(stored.text)))
            literal = _encode_vector(stored.embedding, dim=self._config.embedding_dim)
            rows.append((stored, literal, _document_hash(stored)))

        dsn = await self._secrets.get(self._config.dsn_secret)
        generation_table = self._config.generation_table
        document_table = self._config.document_table
        async with await psycopg.AsyncConnection.connect(
            dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await self._set_session_knobs(connection)
                cursor = await connection.execute(
                    f"SELECT generation_digest FROM {generation_table} "  # noqa: S608
                    "WHERE generation_id = %s FOR UPDATE",
                    (metadata.generation_id,),
                )
                prior = await cursor.fetchone()
                if prior is not None:
                    if str(prior["generation_digest"]) != metadata.generation_digest:
                        raise ValueError("catalog generation id payload conflict")
                    return 0
                await connection.execute(
                    f"""
                    INSERT INTO {generation_table} (
                        generation_id, generation_digest, corpus, catalog_digest,
                        semantic_schema_digest, ontology_release_digest,
                        embedding_space_id, embedding_model_version, embedding_dimension,
                        state, validation_receipt_digest, document_count
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'staged', %s, %s)
                    """,  # noqa: S608
                    (
                        metadata.generation_id,
                        metadata.generation_digest,
                        metadata.corpus,
                        metadata.catalog_digest,
                        metadata.semantic_schema_digest,
                        metadata.ontology_release_digest,
                        metadata.embedding_space_id,
                        metadata.embedding_model_version,
                        metadata.embedding_dimension,
                        metadata.validation_receipt_digest,
                        len(rows),
                    ),
                )
                for document, literal, content_hash in rows:
                    await connection.execute(
                        f"""
                        INSERT INTO {document_table} (
                            generation_id, rule_id, text, neighbor_ids, search_vector,
                            embedding, manifest_digest, surface_digest, content_hash
                        ) VALUES (
                            %s, %s, %s, %s, to_tsvector('simple', %s),
                            %s::vector, %s, %s, %s
                        )
                        """,  # noqa: S608
                        (
                            metadata.generation_id,
                            document.rule_id,
                            document.text,
                            list(document.neighbor_ids),
                            f"{document.rule_id}\n{document.text}",
                            literal,
                            document.manifest_digest,
                            document.surface_digest,
                            content_hash,
                        ),
                    )
        return len(rows)

    async def activate_generation(
        self,
        generation_id: str,
        *,
        expected_generation_digest: str,
        activated_at: datetime,
    ) -> CatalogGenerationMetadata:
        """Atomically retire the old corpus pointer and activate a validated generation."""

        if activated_at.tzinfo is None:
            raise ValueError("catalog generation activation time MUST be timezone-aware")
        dsn = await self._secrets.get(self._config.dsn_secret)
        table = self._config.generation_table
        async with await psycopg.AsyncConnection.connect(
            dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await self._set_session_knobs(connection)
                cursor = await connection.execute(
                    f"SELECT corpus FROM {table} WHERE generation_id = %s",  # noqa: S608
                    (generation_id,),
                )
                identity = await cursor.fetchone()
                if identity is None:
                    raise ValueError("catalog generation is unavailable")
                await connection.execute(
                    _activation_lock_sql(),
                    (f"catalog-search:{identity['corpus']}",),
                )
                cursor = await connection.execute(
                    f"SELECT * FROM {table} WHERE generation_id = %s FOR UPDATE",  # noqa: S608
                    (generation_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise ValueError("catalog generation is unavailable")
                metadata = _row_to_metadata(row)
                if metadata.generation_digest != expected_generation_digest:
                    raise ValueError("catalog generation digest mismatch")
                if metadata.state != "staged":
                    raise ValueError("only a staged catalog generation can be activated")
                if metadata.validation_receipt_digest is None:
                    raise ValueError("catalog generation validation receipt is unavailable")
                await connection.execute(
                    f"UPDATE {table} SET state = 'retired' "  # noqa: S608
                    "WHERE corpus = %s AND state = 'active'",
                    (metadata.corpus,),
                )
                await connection.execute(
                    f"UPDATE {table} SET state = 'active', activated_at = %s "  # noqa: S608
                    "WHERE generation_id = %s",
                    (activated_at, generation_id),
                )
        return replace(metadata, state="active", activated_at=activated_at)

    async def rollback_generation(
        self,
        target_generation_id: str,
        *,
        expected_active_generation_id: str,
        expected_active_generation_digest: str,
        expected_target_generation_digest: str,
        expected_validation_receipt_digest: str,
        ontology_compatibility_receipt: OntologyGenerationCompatibilityReceipt,
        rolled_back_at: datetime,
    ) -> CatalogGenerationRollbackReceipt:
        """Atomically restore a validated retained generation under the corpus lock."""

        dsn = await self._secrets.get(self._config.dsn_secret)
        table = self._config.generation_table
        async with await psycopg.AsyncConnection.connect(
            dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await self._set_session_knobs(connection)
                cursor = await connection.execute(
                    f"SELECT corpus FROM {table} WHERE generation_id = %s",  # noqa: S608
                    (target_generation_id,),
                )
                identity = await cursor.fetchone()
                if identity is None:
                    raise ValueError("catalog rollback target generation is unavailable")
                await connection.execute(
                    _activation_lock_sql(),
                    (f"catalog-search:{identity['corpus']}",),
                )
                cursor = await connection.execute(
                    f"SELECT * FROM {table} WHERE generation_id IN (%s, %s) "  # noqa: S608
                    "ORDER BY generation_id FOR UPDATE",
                    (expected_active_generation_id, target_generation_id),
                )
                rows = await cursor.fetchall()
                generations = {
                    metadata.generation_id: metadata
                    for metadata in (_row_to_metadata(row) for row in rows)
                }
                try:
                    current = generations[expected_active_generation_id]
                    target = generations[target_generation_id]
                except KeyError as exc:
                    raise ValueError("catalog rollback generation is unavailable") from exc
                cursor = await connection.execute(
                    f"SELECT generation_id FROM {table} "  # noqa: S608
                    "WHERE corpus = %s AND state = 'active' FOR UPDATE",
                    (target.corpus,),
                )
                active_row = await cursor.fetchone()
                transition = plan_catalog_generation_rollback(
                    current=current,
                    target=target,
                    active_generation_id=(
                        str(active_row["generation_id"]) if active_row is not None else None
                    ),
                    expected_active_generation_digest=expected_active_generation_digest,
                    expected_target_generation_digest=expected_target_generation_digest,
                    expected_validation_receipt_digest=expected_validation_receipt_digest,
                    ontology_compatibility_receipt=ontology_compatibility_receipt,
                    rolled_back_at=rolled_back_at,
                )
                if transition.already_applied:
                    return transition.receipt
                await connection.execute(
                    f"UPDATE {table} SET state = 'retired' "  # noqa: S608
                    "WHERE generation_id = %s AND state = 'active'",
                    (expected_active_generation_id,),
                )
                await connection.execute(
                    f"UPDATE {table} SET state = 'active', activated_at = %s "  # noqa: S608
                    "WHERE generation_id = %s AND state = 'retired'",
                    (rolled_back_at, target_generation_id),
                )
        return transition.receipt

    async def active_generation(
        self, corpus: CatalogCorpus = "active"
    ) -> CatalogGenerationMetadata | None:
        dsn = await self._secrets.get(self._config.dsn_secret)
        table = self._config.generation_table
        async with await psycopg.AsyncConnection.connect(
            dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await self._set_session_knobs(connection)
                cursor = await connection.execute(
                    f"SELECT * FROM {table} WHERE corpus = %s AND state = 'active'",  # noqa: S608
                    (corpus,),
                )
                row = await cursor.fetchone()
        return _row_to_metadata(row) if row is not None else None

    async def search(
        self,
        query: str,
        *,
        k: int,
        corpus: CatalogCorpus,
        expected_catalog_digest: str | None,
    ) -> Sequence[CatalogSearchResult]:
        normalized_query = query.strip()
        if not normalized_query or k <= 0:
            return ()
        metadata = await self.active_generation(corpus)
        if metadata is None:
            raise CatalogGenerationStaleError("active catalog generation is unavailable")
        if (
            expected_catalog_digest is not None
            and metadata.catalog_digest != expected_catalog_digest
        ):
            raise CatalogGenerationStaleError("active catalog generation is stale")
        query_vector = await self._embedder.embed(normalized_query)
        literal = _encode_vector(query_vector, dim=self._config.embedding_dim)
        dsn = await self._secrets.get(self._config.dsn_secret)
        async with await psycopg.AsyncConnection.connect(
            dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await self._set_session_knobs(connection)
                cursor = await connection.execute(
                    _generation_search_sql(self._config.document_table),
                    (
                        normalized_query,
                        normalized_query,
                        literal,
                        normalized_query,
                        metadata.generation_id,
                        int(k),
                    ),
                )
                rows = await cursor.fetchall()
        return tuple(_row_to_result(row, metadata) for row in rows)

    async def _set_session_knobs(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            f"SET LOCAL statement_timeout = {int(self._config.statement_timeout_ms)}"
        )
        await connection.execute(f"SET LOCAL ivfflat.probes = {int(self._config.ivfflat_probes)}")


def _generation_search_sql(table: str) -> str:
    return f"""
        WITH scored AS (
            SELECT document.rule_id,
                   lower(document.rule_id) = lower(%s) AS exact_id,
                   ts_rank_cd(document.search_vector, plainto_tsquery('simple', %s))
                       AS lexical_score,
                   1.0 - (document.embedding <=> %s::vector) AS semantic_score,
                   COALESCE(neighbor.score, 0.0) AS neighbor_score
              FROM {table} AS document
              LEFT JOIN LATERAL (
                  SELECT MAX(similarity(neighbor_id, %s)) AS score
                    FROM unnest(document.neighbor_ids) AS neighbor_id
              ) AS neighbor ON TRUE
             WHERE document.generation_id = %s
        ), ranked AS (
            SELECT scored.*,
                   row_number() OVER (ORDER BY lexical_score DESC, rule_id ASC) AS lexical_rank,
                   row_number() OVER (ORDER BY semantic_score DESC, rule_id ASC) AS semantic_rank
              FROM scored
        ), fused AS (
            SELECT ranked.*,
                   1.0 / (60.0 + lexical_rank) + 1.0 / (60.0 + semantic_rank)
                       AS fusion_score
              FROM ranked
        )
        SELECT rule_id, exact_id, lexical_score, semantic_score, neighbor_score,
               fusion_score,
               exact_id::int + neighbor_score + fusion_score + lexical_score + semantic_score
                   AS total_score
          FROM fused
         WHERE exact_id OR lexical_score > 0 OR semantic_score >= 0.35 OR neighbor_score >= 0.3
         ORDER BY exact_id DESC, neighbor_score DESC, fusion_score DESC,
                  lexical_score DESC, semantic_score DESC, rule_id ASC
         LIMIT %s
        """  # noqa: S608


def _activation_lock_sql() -> str:
    """Return the transaction lock used to serialize one corpus pointer."""

    return "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))"


def _row_to_metadata(row: Mapping[str, Any]) -> CatalogGenerationMetadata:
    return CatalogGenerationMetadata(
        generation_id=str(row["generation_id"]),
        generation_digest=str(row["generation_digest"]),
        corpus=str(row["corpus"]),  # type: ignore[arg-type]
        catalog_digest=str(row["catalog_digest"]),
        semantic_schema_digest=str(row["semantic_schema_digest"]),
        ontology_release_digest=str(row["ontology_release_digest"]),
        embedding_space_id=str(row["embedding_space_id"]),
        embedding_model_version=str(row["embedding_model_version"]),
        embedding_dimension=int(row["embedding_dimension"]),
        state=str(row["state"]),  # type: ignore[arg-type]
        validation_receipt_digest=(
            str(row["validation_receipt_digest"])
            if row["validation_receipt_digest"] is not None
            else None
        ),
        activated_at=row["activated_at"],
    )


def _row_to_result(
    row: Mapping[str, Any], metadata: CatalogGenerationMetadata
) -> CatalogSearchResult:
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
        corpus=metadata.corpus,
        generation_id=metadata.generation_id,
        generation_digest=metadata.generation_digest,
        catalog_digest=metadata.catalog_digest,
    )


def _document_hash(document: CatalogSearchDocument) -> str:
    payload = {
        "rule_id": document.rule_id,
        "text": document.text,
        "neighbor_ids": document.neighbor_ids,
        "embedding": document.embedding,
        "manifest_digest": document.manifest_digest,
        "surface_digest": document.surface_digest,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "PgvectorCatalogGenerationConfig",
    "PgvectorCatalogGenerationStore",
]
