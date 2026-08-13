"""Durable PostgreSQL and pgvector adapter for catalog search generations."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Final, cast

import psycopg
from psycopg.rows import dict_row

from fdai.shared.ontology.compatibility import OntologyGenerationCompatibilityReceipt
from fdai.shared.providers.catalog_search import (
    CatalogCorpus,
    CatalogDocumentDigestChunk,
    CatalogDocumentDigestManifest,
    CatalogDocumentKind,
    CatalogGenerationMetadata,
    CatalogGenerationRollbackReceipt,
    CatalogGenerationStaleError,
    CatalogGenerationState,
    CatalogSearchDocument,
    CatalogSearchResult,
    CatalogSemanticIndex,
    Embedder,
    build_document_digest_manifest,
    catalog_search_document_digest,
)

_EMBEDDING_DIM: Final[int] = 384
_MIN_SCORE: Final[float] = 0.2


@dataclass(frozen=True, slots=True)
class PostgresCatalogSemanticIndexConfig:
    """Bounded connection, vector, and batch settings for catalog search."""

    dsn: str
    statement_timeout_ms: int = 30_000
    connect_timeout_s: int = 10
    ivfflat_probes: int = 10
    write_batch_size: int = 500
    embedding_batch_size: int = 16
    embedding_dimension: int = _EMBEDDING_DIM

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresCatalogSemanticIndexConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("database timeouts MUST be >= 1")
        if self.ivfflat_probes < 1:
            raise ValueError("ivfflat_probes MUST be >= 1")
        if not 1 <= self.write_batch_size <= 10_000:
            raise ValueError("write_batch_size MUST be in [1, 10000]")
        if not 1 <= self.embedding_batch_size <= 128:
            raise ValueError("embedding_batch_size MUST be in [1, 128]")
        if self.embedding_dimension != _EMBEDDING_DIM:
            raise ValueError(f"embedding_dimension MUST be {_EMBEDDING_DIM}")


class PostgresCatalogSemanticIndex(CatalogSemanticIndex):
    """Persist complete candidate-only generations behind corpus-local locks."""

    def __init__(
        self,
        *,
        config: PostgresCatalogSemanticIndexConfig,
        embedder: Embedder,
    ) -> None:
        self._config = config
        self._embedder = embedder

    async def upsert(self, documents: Sequence[CatalogSearchDocument]) -> int:
        prepared = await self._prepare_documents(documents)
        if not prepared:
            return 0
        async with await self._connect() as connection, connection.transaction():
            await self._set_session_knobs(connection)
            await self._upsert_documents(connection, prepared)
        return len(prepared)

    async def synchronize(self, documents: Sequence[CatalogSearchDocument]) -> int:
        prepared = await self._prepare_documents(documents)
        identifiers = tuple(item.rule_id for item in prepared)
        async with await self._connect() as connection, connection.transaction():
            await self._set_session_knobs(connection)
            prior_cursor = await connection.execute(
                "SELECT rule_id, content_hash FROM catalog_search_document"
            )
            prior = {
                str(row["rule_id"]): str(row["content_hash"])
                for row in await prior_cursor.fetchall()
            }
            await connection.execute(
                "DELETE FROM catalog_search_document WHERE NOT (rule_id = ANY(%s::text[]))",
                (list(identifiers),),
            )
            await self._upsert_documents(connection, prepared)
        current = {item.rule_id: catalog_search_document_digest(item)[7:] for item in prepared}
        return len(set(prior).symmetric_difference(current)) + sum(
            prior[rule_id] != digest for rule_id, digest in current.items() if rule_id in prior
        )

    async def stage_generation(
        self,
        metadata: CatalogGenerationMetadata,
        documents: Sequence[CatalogSearchDocument],
    ) -> int:
        if metadata.state != "staged":
            raise ValueError("only staged catalog generations can be written")
        if metadata.embedding_dimension != self._config.embedding_dimension:
            raise ValueError("catalog generation embedding dimension mismatch")
        normalized = _normalize_documents(metadata, documents)
        _verify_document_identity(metadata, normalized)
        prepared = await self._prepare_documents(normalized)
        async with await self._connect() as connection, connection.transaction():
            await self._set_session_knobs(connection)
            existing = await self._load_generation(
                connection, metadata.generation_id, for_update=True
            )
            if existing is not None:
                existing_metadata, existing_documents = existing
                if existing_metadata == metadata and _without_embeddings(
                    existing_documents
                ) == _without_embeddings(normalized):
                    return 0
                raise ValueError("catalog generation id payload conflict")
            await connection.execute(
                "INSERT INTO catalog_search_generation "
                "(generation_id, generation_digest, corpus, catalog_digest, "
                "semantic_schema_digest, ontology_release_digest, embedding_space_id, "
                "embedding_model_version, embedding_dimension, state, "
                "validation_receipt_digest, document_count, document_digest_root, "
                "document_digest_chunks, inline_document_digests) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)",
                _metadata_insert_values(metadata),
            )
            cursor = connection.cursor()
            for offset in range(0, len(prepared), self._config.write_batch_size):
                rows = [
                    _document_insert_values(metadata.generation_id, ordinal, item)
                    for ordinal, item in enumerate(
                        prepared[offset : offset + self._config.write_batch_size],
                        start=offset,
                    )
                ]
                await cursor.executemany(
                    "INSERT INTO catalog_search_generation_document "
                    "(generation_id, ordinal, rule_id, text, neighbor_ids, document_kind, "
                    "search_vector, embedding, manifest_digest, surface_digest, content_hash) "
                    "VALUES (%s, %s, %s, %s, %s, %s, to_tsvector('simple', %s), "
                    "%s::vector, %s, %s, %s)",
                    rows,
                )
        return len(prepared)

    async def activate_generation(
        self,
        generation_id: str,
        *,
        expected_generation_digest: str,
        expected_active_generation_id: str | None,
        expected_active_generation_digest: str | None,
        activated_at: datetime,
    ) -> CatalogGenerationMetadata:
        if activated_at.tzinfo is None:
            raise ValueError("catalog generation activation time MUST be timezone-aware")
        if (expected_active_generation_id is None) != (expected_active_generation_digest is None):
            raise ValueError("expected active generation identity MUST be supplied together")
        async with await self._connect() as connection, connection.transaction():
            await self._set_session_knobs(connection)
            corpus = await self._generation_corpus(connection, generation_id)
            await _lock_corpus(connection, corpus)
            loaded = await self._load_generation(connection, generation_id, for_update=True)
            if loaded is None:
                raise ValueError("catalog generation is unavailable")
            metadata, _documents = loaded
            if metadata.generation_digest != expected_generation_digest:
                raise ValueError("catalog generation digest mismatch")
            active_cursor = await connection.execute(
                "SELECT generation_id FROM catalog_search_generation "
                "WHERE corpus=%s AND state='active' FOR UPDATE",
                (metadata.corpus,),
            )
            active_rows = await active_cursor.fetchall()
            if len(active_rows) > 1:
                raise CatalogGenerationStaleError("active catalog generation is ambiguous")
            active_id = str(active_rows[0]["generation_id"]) if active_rows else None
            if metadata.state == "active":
                if active_id == generation_id and metadata.activated_at == activated_at:
                    return metadata
                raise CatalogGenerationStaleError("active catalog generation is stale")
            if metadata.state == "retired":
                raise CatalogGenerationStaleError("active catalog generation is stale")
            if metadata.state != "staged" or metadata.validation_receipt_digest is None:
                raise ValueError("catalog generation is not validated and staged")
            if expected_active_generation_id is None:
                if active_id is not None:
                    raise CatalogGenerationStaleError("active catalog generation is stale")
            elif active_id != expected_active_generation_id:
                raise CatalogGenerationStaleError("active catalog generation is stale")
            else:
                active_loaded = await self._load_generation(
                    connection,
                    expected_active_generation_id,
                    for_update=True,
                )
                if active_loaded is None:
                    raise CatalogGenerationStaleError("active catalog generation is stale")
                active, _active_documents = active_loaded
                if (
                    active.generation_digest != expected_active_generation_digest
                    or active.state != "active"
                ):
                    raise CatalogGenerationStaleError("active catalog generation is stale")
                if active.activated_at is None or activated_at < active.activated_at:
                    raise ValueError(
                        "catalog generation activation time precedes active generation"
                    )
            await connection.execute(
                "UPDATE catalog_search_generation SET state='retired' "
                "WHERE corpus=%s AND state='active'",
                (metadata.corpus,),
            )
            await connection.execute(
                "UPDATE catalog_search_generation SET state='active', activated_at=%s "
                "WHERE generation_id=%s",
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
        if rolled_back_at.tzinfo is None:
            raise ValueError("catalog generation rollback time MUST be timezone-aware")
        async with await self._connect() as connection, connection.transaction():
            await self._set_session_knobs(connection)
            corpus = await self._generation_corpus(connection, target_generation_id)
            await _lock_corpus(connection, corpus)
            target_loaded = await self._load_generation(
                connection, target_generation_id, for_update=True
            )
            current_loaded = await self._load_generation(
                connection, expected_active_generation_id, for_update=True
            )
            if target_loaded is None or current_loaded is None:
                raise ValueError("catalog rollback generation is unavailable")
            target, _target_documents = target_loaded
            current, _current_documents = current_loaded
            if target.corpus != current.corpus:
                raise ValueError("catalog rollback generations MUST share one corpus")
            if (
                target.state == "active"
                and current.state == "retired"
                and target.activated_at == rolled_back_at
            ):
                if current.generation_digest != expected_active_generation_digest:
                    raise ValueError("active catalog generation digest mismatch")
                if target.generation_digest != expected_target_generation_digest:
                    raise ValueError("target catalog generation digest mismatch")
                if target.validation_receipt_digest != expected_validation_receipt_digest:
                    raise ValueError("target catalog validation receipt mismatch")
                return CatalogGenerationRollbackReceipt(
                    retired_generation=current,
                    reactivated_generation=target,
                    validation_receipt_digest=expected_validation_receipt_digest,
                    ontology_compatibility_receipt=ontology_compatibility_receipt,
                    rolled_back_at=rolled_back_at,
                )
            if current.state != "active":
                raise CatalogGenerationStaleError("active catalog generation is stale")
            if current.generation_digest != expected_active_generation_digest:
                raise ValueError("active catalog generation digest mismatch")
            if target.generation_digest != expected_target_generation_digest:
                raise ValueError("target catalog generation digest mismatch")
            if target.validation_receipt_digest != expected_validation_receipt_digest:
                raise ValueError("target catalog validation receipt mismatch")
            if target.state != "retired" or target.activated_at is None:
                raise ValueError("target catalog generation is not retained")
            if (
                current.activated_at is None
                or target.activated_at > rolled_back_at
                or current.activated_at > rolled_back_at
            ):
                raise ValueError("catalog rollback time precedes generation activation")
            retired = replace(current, state="retired")
            reactivated = replace(target, state="active", activated_at=rolled_back_at)
            receipt = CatalogGenerationRollbackReceipt(
                retired_generation=retired,
                reactivated_generation=reactivated,
                validation_receipt_digest=expected_validation_receipt_digest,
                ontology_compatibility_receipt=ontology_compatibility_receipt,
                rolled_back_at=rolled_back_at,
            )
            await connection.execute(
                "UPDATE catalog_search_generation SET state='retired' WHERE generation_id=%s",
                (current.generation_id,),
            )
            await connection.execute(
                "UPDATE catalog_search_generation SET state='active', activated_at=%s "
                "WHERE generation_id=%s",
                (rolled_back_at, target.generation_id),
            )
        return receipt

    async def active_generation(
        self,
        corpus: CatalogCorpus = "active",
    ) -> CatalogGenerationMetadata | None:
        async with await self._connect() as connection, connection.transaction():
            await self._set_session_knobs(connection)
            await _lock_corpus(connection, corpus, shared=True)
            cursor = await connection.execute(
                "SELECT generation_id FROM catalog_search_generation "
                "WHERE corpus=%s AND state='active'",
                (corpus,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            loaded = await self._load_generation(connection, str(row["generation_id"]))
            return loaded[0] if loaded is not None else None

    async def search(
        self,
        query: str,
        *,
        k: int = 20,
        corpus: CatalogCorpus = "active",
        expected_catalog_digest: str | None = None,
        candidate_rule_ids: frozenset[str] | None = None,
    ) -> Sequence[CatalogSearchResult]:
        if not 1 <= k <= 100 or not query.strip():
            return ()
        query_vector = await self._embedder.embed(query)
        vector = _encode_vector(query_vector, self._config.embedding_dimension)
        async with await self._connect() as connection, connection.transaction():
            await self._set_session_knobs(connection)
            await _lock_corpus(connection, corpus, shared=True)
            cursor = await connection.execute(
                "SELECT generation_id FROM catalog_search_generation "
                "WHERE corpus=%s AND state='active'",
                (corpus,),
            )
            row = await cursor.fetchone()
            if row is None:
                if expected_catalog_digest is not None:
                    raise CatalogGenerationStaleError("active catalog generation is unavailable")
                return ()
            loaded = await self._load_generation(connection, str(row["generation_id"]))
            if loaded is None:
                raise CatalogGenerationStaleError("active catalog generation is unavailable")
            metadata, _documents = loaded
            if (
                expected_catalog_digest is not None
                and metadata.catalog_digest != expected_catalog_digest
            ):
                raise CatalogGenerationStaleError("active catalog generation is stale")
            results = await connection.execute(
                "WITH distances AS (SELECT d.rule_id, d.document_kind, "
                "CASE WHEN lower(d.rule_id)=lower(%s) THEN 1.0 ELSE 0.0 END AS exact, "
                "ts_rank_cd(d.search_vector, plainto_tsquery('simple', %s)) AS lexical, "
                "d.embedding <=> %s::vector AS distance "
                "FROM catalog_search_generation_document d WHERE d.generation_id=%s "
                "AND (%s::text[] IS NULL OR d.rule_id=ANY(%s::text[]))), "
                "scored AS (SELECT rule_id, document_kind, exact, lexical, "
                "CASE WHEN distance='NaN'::double precision THEN 0.0 "
                "ELSE GREATEST(0.0, 1.0 - distance) END AS semantic FROM distances) "
                "SELECT rule_id, document_kind, exact, lexical, semantic, "
                "exact + lexical + semantic AS score FROM scored "
                "WHERE exact + lexical + semantic >= %s "
                "ORDER BY score DESC, rule_id ASC LIMIT %s",
                (
                    query,
                    query,
                    vector,
                    metadata.generation_id,
                    list(candidate_rule_ids) if candidate_rule_ids is not None else None,
                    list(candidate_rule_ids) if candidate_rule_ids is not None else None,
                    _MIN_SCORE,
                    int(k),
                ),
            )
            rows = await results.fetchall()
        return tuple(
            CatalogSearchResult(
                rule_id=str(item["rule_id"]),
                score=float(item["score"]),
                match="exact_id" if float(item["exact"]) else "hybrid",
                components={
                    "exact": float(item["exact"]),
                    "lexical": float(item["lexical"]),
                    "semantic": float(item["semantic"]),
                },
                corpus=metadata.corpus,
                generation_id=metadata.generation_id,
                generation_digest=metadata.generation_digest,
                catalog_digest=metadata.catalog_digest,
                document_kind=cast(CatalogDocumentKind, str(item["document_kind"])),
            )
            for item in rows
        )

    async def _prepare_documents(
        self,
        documents: Sequence[CatalogSearchDocument],
    ) -> tuple[CatalogSearchDocument, ...]:
        prepared: list[CatalogSearchDocument] = []
        for offset in range(0, len(documents), self._config.embedding_batch_size):
            batch = documents[offset : offset + self._config.embedding_batch_size]
            vectors = await asyncio.gather(
                *(
                    self._embedder.embed(item.text)
                    if not item.embedding
                    else _identity(item.embedding)
                    for item in batch
                )
            )
            prepared.extend(
                replace(item, embedding=tuple(float(value) for value in vector))
                for item, vector in zip(batch, vectors, strict=True)
            )
        for item in prepared:
            _encode_vector(item.embedding, self._config.embedding_dimension)
        return tuple(prepared)

    async def _load_generation(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        generation_id: str,
        *,
        for_update: bool = False,
    ) -> tuple[CatalogGenerationMetadata, tuple[CatalogSearchDocument, ...]] | None:
        suffix = " FOR UPDATE" if for_update else ""
        cursor = await connection.execute(
            "SELECT generation_id, generation_digest, corpus, catalog_digest, "
            "semantic_schema_digest, ontology_release_digest, embedding_space_id, "
            "embedding_model_version, embedding_dimension, state, "
            "validation_receipt_digest, document_count, document_digest_root, "
            "document_digest_chunks, inline_document_digests, activated_at "
            "FROM catalog_search_generation WHERE generation_id=%s" + suffix,
            (generation_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        metadata = _metadata_from_row(row)
        document_cursor = await connection.execute(
            "SELECT ordinal, rule_id, text, neighbor_ids, document_kind, manifest_digest, "
            "surface_digest, content_hash FROM catalog_search_generation_document "
            "WHERE generation_id=%s ORDER BY ordinal",
            (generation_id,),
        )
        rows = await document_cursor.fetchall()
        if tuple(int(item["ordinal"]) for item in rows) != tuple(range(len(rows))):
            raise ValueError("catalog generation stored document ordinals are not contiguous")
        documents = tuple(_document_from_row(item, metadata) for item in rows)
        if len(documents) != metadata.document_digest_manifest.document_count:
            raise ValueError("catalog generation stored document count mismatch")
        for item, stored in zip(documents, rows, strict=True):
            if catalog_search_document_digest(item)[7:] != str(stored["content_hash"]):
                raise ValueError("catalog generation stored document hash mismatch")
        _verify_document_identity(metadata, documents)
        return metadata, documents

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _generation_corpus(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        generation_id: str,
    ) -> CatalogCorpus:
        cursor = await connection.execute(
            "SELECT corpus FROM catalog_search_generation WHERE generation_id=%s",
            (generation_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError("catalog generation is unavailable")
        return cast(CatalogCorpus, str(row["corpus"]))

    async def _set_session_knobs(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )
        await connection.execute(
            "SELECT set_config('ivfflat.probes', %s, true)",
            (str(self._config.ivfflat_probes),),
        )

    async def _upsert_documents(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        documents: Sequence[CatalogSearchDocument],
    ) -> None:
        cursor = connection.cursor()
        for offset in range(0, len(documents), self._config.write_batch_size):
            rows = [
                (
                    item.rule_id,
                    item.text,
                    list(item.neighbor_ids),
                    item.text,
                    _encode_vector(item.embedding, self._config.embedding_dimension),
                    catalog_search_document_digest(item)[7:],
                )
                for item in documents[offset : offset + self._config.write_batch_size]
            ]
            await cursor.executemany(
                "INSERT INTO catalog_search_document "
                "(rule_id, text, neighbor_ids, search_vector, embedding, content_hash) "
                "VALUES (%s, %s, %s, to_tsvector('simple', %s), %s::vector, %s) "
                "ON CONFLICT (rule_id) DO UPDATE SET text=EXCLUDED.text, "
                "neighbor_ids=EXCLUDED.neighbor_ids, search_vector=EXCLUDED.search_vector, "
                "embedding=EXCLUDED.embedding, content_hash=EXCLUDED.content_hash, "
                "updated_at=NOW()",
                rows,
            )


async def _identity(values: Sequence[float]) -> Sequence[float]:
    return values


def _encode_vector(values: Sequence[float], dimension: int) -> str:
    if len(values) != dimension:
        raise ValueError(f"embedding dim MUST be {dimension}; got {len(values)}")
    normalized = tuple(float(value) for value in values)
    if any(not math.isfinite(value) for value in normalized):
        raise ValueError("embedding values MUST be finite")
    return "[" + ",".join(f"{value:.9g}" for value in normalized) + "]"


def _normalize_documents(
    metadata: CatalogGenerationMetadata,
    documents: Sequence[CatalogSearchDocument],
) -> tuple[CatalogSearchDocument, ...]:
    if not documents:
        raise ValueError("catalog generation documents MUST be non-empty")
    normalized = tuple(
        replace(item, corpus=metadata.corpus, generation_id=metadata.generation_id)
        for item in documents
    )
    identifiers = tuple(item.rule_id for item in normalized)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("catalog generation document ids MUST be unique")
    return normalized


def _verify_document_identity(
    metadata: CatalogGenerationMetadata,
    documents: Sequence[CatalogSearchDocument],
) -> None:
    actual = build_document_digest_manifest(
        tuple(catalog_search_document_digest(item) for item in documents)
    )
    if actual != metadata.document_digest_manifest:
        raise ValueError("catalog generation document digest manifest mismatch")


def _metadata_insert_values(metadata: CatalogGenerationMetadata) -> tuple[object, ...]:
    manifest = metadata.document_digest_manifest
    return (
        metadata.generation_id,
        metadata.generation_digest,
        metadata.corpus,
        metadata.catalog_digest,
        metadata.semantic_schema_digest,
        metadata.ontology_release_digest,
        metadata.embedding_space_id,
        metadata.embedding_model_version,
        metadata.embedding_dimension,
        metadata.state,
        metadata.validation_receipt_digest,
        manifest.document_count,
        manifest.document_digest_root,
        json.dumps([_chunk_mapping(item) for item in manifest.chunks]),
        json.dumps(manifest.inline_document_digests),
    )


def _document_insert_values(
    generation_id: str,
    ordinal: int,
    document: CatalogSearchDocument,
) -> tuple[object, ...]:
    return (
        generation_id,
        ordinal,
        document.rule_id,
        document.text,
        list(document.neighbor_ids),
        document.document_kind,
        document.text,
        _encode_vector(document.embedding, _EMBEDDING_DIM),
        document.manifest_digest,
        document.surface_digest,
        catalog_search_document_digest(document)[7:],
    )


def _metadata_from_row(row: dict[str, Any]) -> CatalogGenerationMetadata:
    chunks_raw = _json_array(row["document_digest_chunks"], "document_digest_chunks")
    inline_raw = _json_array(row["inline_document_digests"], "inline_document_digests")
    chunks = tuple(_chunk_from_value(item) for item in chunks_raw)
    manifest = CatalogDocumentDigestManifest(
        document_count=int(row["document_count"]),
        document_digest_root=str(row["document_digest_root"]),
        chunks=chunks,
        inline_document_digests=tuple(str(item) for item in inline_raw),
    )
    return CatalogGenerationMetadata(
        generation_id=str(row["generation_id"]),
        generation_digest=str(row["generation_digest"]),
        corpus=cast(CatalogCorpus, str(row["corpus"])),
        catalog_digest=str(row["catalog_digest"]),
        semantic_schema_digest=str(row["semantic_schema_digest"]),
        ontology_release_digest=str(row["ontology_release_digest"]),
        embedding_space_id=str(row["embedding_space_id"]),
        embedding_model_version=str(row["embedding_model_version"]),
        embedding_dimension=int(row["embedding_dimension"]),
        document_digest_manifest=manifest,
        state=cast(CatalogGenerationState, str(row["state"])),
        validation_receipt_digest=(
            str(row["validation_receipt_digest"])
            if row["validation_receipt_digest"] is not None
            else None
        ),
        activated_at=cast(datetime | None, row["activated_at"]),
    )


def _document_from_row(
    row: dict[str, Any],
    metadata: CatalogGenerationMetadata,
) -> CatalogSearchDocument:
    return CatalogSearchDocument(
        rule_id=str(row["rule_id"]),
        text=str(row["text"]),
        neighbor_ids=tuple(str(item) for item in row["neighbor_ids"]),
        document_kind=cast(CatalogDocumentKind, str(row["document_kind"])),
        corpus=metadata.corpus,
        generation_id=metadata.generation_id,
        manifest_digest=str(row["manifest_digest"]) if row["manifest_digest"] else None,
        surface_digest=str(row["surface_digest"]) if row["surface_digest"] else None,
    )


def _without_embeddings(
    documents: Sequence[CatalogSearchDocument],
) -> tuple[CatalogSearchDocument, ...]:
    return tuple(replace(item, embedding=()) for item in documents)


def _chunk_mapping(chunk: CatalogDocumentDigestChunk) -> dict[str, object]:
    return {
        "index": chunk.index,
        "document_count": chunk.document_count,
        "document_digest_root": chunk.document_digest_root,
    }


def _json_array(value: object, field: str) -> list[object]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list):
        raise ValueError(f"{field} MUST be a JSON array")
    return value


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} MUST be an object")
    return {str(key): item for key, item in value.items()}


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} MUST be an integer")
    return value


def _chunk_from_value(value: object) -> CatalogDocumentDigestChunk:
    mapping = _mapping(value, "document digest chunk")
    return CatalogDocumentDigestChunk(
        index=_integer(_required(mapping, "index", "chunk index"), "chunk index"),
        document_count=_integer(
            _required(mapping, "document_count", "chunk document_count"),
            "chunk document_count",
        ),
        document_digest_root=str(
            _required(mapping, "document_digest_root", "chunk document_digest_root")
        ),
    )


def _required(mapping: dict[str, object], key: str, field: str) -> object:
    if key not in mapping:
        raise ValueError(f"{field} is required")
    return mapping[key]


async def _lock_corpus(
    connection: psycopg.AsyncConnection[Any],
    corpus: CatalogCorpus,
    *,
    shared: bool = False,
) -> None:
    function = "pg_advisory_xact_lock_shared" if shared else "pg_advisory_xact_lock"
    await connection.execute(
        f"SELECT {function}(hashtextextended(%s, 0))",  # noqa: S608 - fixed function names
        (f"catalog-search:{corpus}",),
    )


__all__ = ["PostgresCatalogSemanticIndex", "PostgresCatalogSemanticIndexConfig"]
