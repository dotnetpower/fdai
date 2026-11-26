"""knowledge_chunk: pgvector-backed store for free-form RAG grounding

Revision ID: 20260712_0009
Revises: 20260709_0001
Create Date: 2026-07-12 00:00:00

Backs
:class:`~fdai.delivery.pgvector.knowledge.PgvectorKnowledgeSource` with a
persistent Postgres+pgvector table so ingested operator documents
(runbooks, architecture notes, wiki exports) survive process restarts and
ground T2 reasoning. The in-memory
:class:`~fdai.shared.providers.knowledge.EmbeddingKnowledgeSource` mirrors
the same ``KnowledgeSource`` contract for unit tests; this migration only
creates the physical backing.

Columns
-------
- ``chunk_id`` - stable ``"<doc_id>#<ordinal>"`` primary key so re-ingesting
  the same document upserts its chunks in place rather than duplicating.
- ``doc_id`` - the source document id (many chunks per document).
- ``text`` - the chunk body used to render a grounded citation snippet.
- ``source_ref`` - the citation handle (URI / wiki page id / path).
- ``embedding`` - ``vector(384)`` - matches the local
  ``sentence-transformers/all-MiniLM-L6-v2`` embedding dimension used by
  the Phase-2 EmbeddingModel adapter, identical to ``t1_pattern_library``.
- ``metadata`` - JSONB, adapter-neutral, never carries secrets.
- ``created_at`` - server timestamp for audit / eviction.

Indexes
-------
- ``IVFFlat(embedding vector_cosine_ops, lists=100)`` for approximate
  nearest-neighbour cosine search, matching the pattern-library index.
- ``idx_knowledge_chunk_doc_id`` - delete/replace all chunks of a document.

The ``vector`` extension is created idempotently for callers that run this
migration in isolation; the base chain already installed it via
``20260705_0002_layered_cache``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260712_0009"
down_revision: str | None = "20260709_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    op.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_chunk (
            chunk_id     TEXT PRIMARY KEY,
            doc_id       TEXT NOT NULL,
            text         TEXT NOT NULL,
            source_ref   TEXT NOT NULL,
            embedding    vector(384) NOT NULL,
            metadata     JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("CREATE INDEX idx_knowledge_chunk_doc_id ON knowledge_chunk(doc_id);")

    # IVFFlat cosine index. Building on an empty table only emits a NOTICE;
    # pgvector recommends lists ~= rows/1000, and 100 is the small-corpus
    # default matching the T1 pattern library.
    op.execute("""
        CREATE INDEX idx_knowledge_chunk_embedding
            ON knowledge_chunk
         USING ivfflat (embedding vector_cosine_ops)
          WITH (lists = 100);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_knowledge_chunk_embedding;")
    op.execute("DROP INDEX IF EXISTS idx_knowledge_chunk_doc_id;")
    op.execute("DROP TABLE IF EXISTS knowledge_chunk;")
