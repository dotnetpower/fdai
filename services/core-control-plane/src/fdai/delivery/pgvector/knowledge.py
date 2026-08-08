"""PgvectorKnowledgeSource - persistent :class:`KnowledgeSource` on Postgres+pgvector.

Realizes the
:class:`~fdai.shared.providers.knowledge.KnowledgeSource` Protocol against
the ``knowledge_chunk`` table created by
``alembic/versions/20260712_0009_knowledge_base.py``. It is the production
counterpart of the in-memory
:class:`~fdai.shared.providers.knowledge.EmbeddingKnowledgeSource`
reference: same ``ingest`` / ``search`` contract, so the two are
swappable and a parity test can assert identical top-K rank on a fixed
corpus.

Design boundaries (mirrors
:mod:`fdai.delivery.persistence.pgvector_pattern_library`)
------------------------------------------------------------------

- ``core/`` never imports this module; the composition root binds it in
  place of the in-memory default.
- **Reuses the embedding seam** - the same injected
  :class:`~fdai.shared.providers.knowledge.Embedder` the reference uses.
  The adapter never re-implements embedding; it embeds each chunk on
  ingest and the query on search through that seam.
- Chunking is the shared, deterministic
  :func:`~fdai.shared.providers.knowledge.chunk_text`, so a document
  produces the exact same chunk set as the reference - the precondition
  for rank parity.
- psycopg 3 (already a repo dep) with the pgvector text literal
  (``'[a,b,c]'::vector``); no new package in the lockfile, no optional
  ``pgvector`` Python dependency.
- The DSN is resolved through the injected
  :class:`~fdai.shared.providers.secret_provider.SecretProvider` at call
  time (never env-baked, never logged).

Safety / cost invariants: bounded ``statement_timeout`` + ``connect_timeout``
(fail fast rather than block the event loop), a query-time ``ivfflat.probes``
recall knob, and ``INSERT ... ON CONFLICT`` upsert keyed on ``chunk_id`` so
re-ingesting a document is idempotent.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.shared.providers.knowledge import (
    Embedder,
    KnowledgeChunk,
    KnowledgeDocument,
    chunk_text,
)
from fdai.shared.providers.secret_provider import SecretProvider

_LOGGER = logging.getLogger("fdai.delivery.pgvector.knowledge")

_EMBEDDING_DIM: Final[int] = 384
_DEFAULT_MAX_CHARS: Final[int] = 1_200
_DEFAULT_OVERLAP: Final[int] = 150
#: Strict ASCII SQL identifier (the ``table`` config is inlined into SQL).
_IDENTIFIER_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _encode_vector(values: Sequence[float], *, dim: int) -> str:
    """Serialize a float sequence into pgvector's text literal format."""
    if len(values) != dim:
        raise ValueError(f"embedding dim MUST be {dim}; got {len(values)}")
    return "[" + ",".join(f"{float(v):.9g}" for v in values) + "]"


@dataclass(frozen=True, slots=True)
class PgvectorKnowledgeConfig:
    """DSN + tuning knobs for the pgvector knowledge source.

    ``dsn_secret`` is the *name* looked up on the injected
    :class:`SecretProvider`; the raw DSN NEVER lives in the config object.
    """

    dsn_secret: str
    table: str = "knowledge_chunk"
    embedding_dim: int = _EMBEDDING_DIM
    top_k: int = 5
    max_chars: int = _DEFAULT_MAX_CHARS
    overlap: int = _DEFAULT_OVERLAP
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10
    ivfflat_probes: int = 10

    def __post_init__(self) -> None:
        if not self.dsn_secret:
            raise ValueError("PgvectorKnowledgeConfig.dsn_secret MUST be non-empty")
        # `table` is inlined into SQL (identifiers cannot be parametrized);
        # restrict it to a strict ASCII SQL identifier so config cannot
        # inject SQL. ``str.isalnum()`` is NOT sufficient - it accepts
        # non-ASCII letters (e.g. Hangul), which are valid Postgres
        # identifiers but never intended here.
        if not _IDENTIFIER_RE.fullmatch(self.table):
            raise ValueError(
                "PgvectorKnowledgeConfig.table MUST be a plain ASCII SQL "
                "identifier ([A-Za-z_][A-Za-z0-9_]*)"
            )
        if self.embedding_dim < 1:
            raise ValueError("embedding_dim MUST be >= 1")
        if self.top_k < 1:
            raise ValueError("top_k MUST be >= 1")
        if self.max_chars <= 0:
            raise ValueError("max_chars MUST be positive")
        if self.overlap < 0 or self.overlap >= self.max_chars:
            raise ValueError("overlap MUST be in [0, max_chars)")
        if self.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        if self.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")
        if self.ivfflat_probes < 1:
            raise ValueError("ivfflat_probes MUST be >= 1")


class PgvectorKnowledgeSource:
    """Async :class:`KnowledgeSource` on the ``knowledge_chunk`` table."""

    def __init__(
        self,
        *,
        config: PgvectorKnowledgeConfig,
        embedder: Embedder,
        secrets: SecretProvider,
    ) -> None:
        self._config: Final[PgvectorKnowledgeConfig] = config
        self._embedder: Final[Embedder] = embedder
        self._secrets: Final[SecretProvider] = secrets

    async def ingest(self, documents: Sequence[KnowledgeDocument]) -> int:
        rows: list[tuple[str, str, str, str, str, str]] = []
        for doc in documents:
            pieces = chunk_text(
                doc.text, max_chars=self._config.max_chars, overlap=self._config.overlap
            )
            for i, piece in enumerate(pieces):
                vector = await self._embedder.embed(piece)
                literal = _encode_vector(vector, dim=self._config.embedding_dim)
                rows.append(
                    (
                        f"{doc.doc_id}#{i}",
                        doc.doc_id,
                        piece,
                        doc.source_ref,
                        literal,
                        json.dumps(dict(doc.metadata), default=str),
                    )
                )
        if not rows:
            return 0

        dsn = await self._secrets.get(self._config.dsn_secret)
        table = self._config.table
        async with await psycopg.AsyncConnection.connect(
            dsn, connect_timeout=self._config.connect_timeout_s
        ) as conn:
            async with conn.transaction():
                await self._set_session_knobs(conn)
                for chunk_id, doc_id, text, source_ref, literal, metadata in rows:
                    await conn.execute(
                        f"""
                        INSERT INTO {table}
                            (chunk_id, doc_id, text, source_ref, embedding, metadata)
                        VALUES (%s, %s, %s, %s, %s::vector, %s::jsonb)
                        ON CONFLICT (chunk_id) DO UPDATE SET
                            doc_id     = EXCLUDED.doc_id,
                            text       = EXCLUDED.text,
                            source_ref = EXCLUDED.source_ref,
                            embedding  = EXCLUDED.embedding,
                            metadata   = EXCLUDED.metadata
                        """,  # noqa: S608 - table is a validated identifier, values are parametrized
                        (chunk_id, doc_id, text, source_ref, literal, metadata),
                    )
        return len(rows)

    async def search(self, query: str, *, k: int = 5) -> Sequence[KnowledgeChunk]:
        if k < 1:
            return ()
        query_vector = await self._embedder.embed(query)
        literal = _encode_vector(query_vector, dim=self._config.embedding_dim)
        dsn = await self._secrets.get(self._config.dsn_secret)
        table = self._config.table
        async with await psycopg.AsyncConnection.connect(
            dsn, row_factory=dict_row, connect_timeout=self._config.connect_timeout_s
        ) as conn:
            async with conn.transaction():
                await self._set_session_knobs(conn)
                cur = await conn.execute(
                    f"""
                    SELECT doc_id,
                           chunk_id,
                           text,
                           source_ref,
                           metadata,
                           1.0 - (embedding <=> %s::vector) AS score
                      FROM {table}
                     WHERE COALESCE(metadata->>'governed_document', 'false') <> 'true'
                     ORDER BY embedding <=> %s::vector ASC
                     LIMIT %s
                    """,  # noqa: S608 - table is a validated identifier, values are parametrized
                    (literal, literal, int(k)),
                )
                fetched = await cur.fetchall()

        chunks = [
            KnowledgeChunk(
                doc_id=str(row["doc_id"]),
                chunk_id=str(row["chunk_id"]),
                text=str(row["text"]),
                source_ref=str(row["source_ref"]),
                score=float(row["score"]),
                metadata=_coerce_metadata(row["metadata"]),
            )
            for row in fetched
        ]
        # Distance-ordered ascending == similarity descending; be defensive.
        chunks.sort(key=lambda c: c.score, reverse=True)
        return tuple(chunks)

    async def _set_session_knobs(self, conn: psycopg.AsyncConnection[Any]) -> None:
        # SET LOCAL cannot parametrize values; inline the validated ints.
        timeout_ms = int(self._config.statement_timeout_ms)
        probes = int(self._config.ivfflat_probes)
        await conn.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
        await conn.execute(f"SET LOCAL ivfflat.probes = {probes}")


def _coerce_metadata(raw: Any) -> dict[str, str]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError as exc:
            raise RuntimeError("knowledge_chunk.metadata is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("knowledge_chunk.metadata is not a JSON object")
        return {str(k): str(v) for k, v in parsed.items()}
    raise RuntimeError(f"knowledge_chunk.metadata unexpected type {type(raw).__name__}")


__all__ = [
    "PgvectorKnowledgeConfig",
    "PgvectorKnowledgeSource",
]
