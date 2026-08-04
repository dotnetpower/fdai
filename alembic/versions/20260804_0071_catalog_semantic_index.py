"""add persistent catalog semantic index

Revision ID: 20260804_0071
Revises: 20260803_0070
Create Date: 2026-08-04 00:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260804_0071"
down_revision: str | None = "20260803_0070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    op.execute(
        """
        CREATE TABLE catalog_search_document (
            rule_id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            neighbor_ids TEXT[] NOT NULL,
            search_vector TSVECTOR NOT NULL,
            embedding vector(384) NOT NULL,
            content_hash CHAR(64) NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_catalog_search_rule_id_nonempty CHECK (length(rule_id) > 0),
            CONSTRAINT ck_catalog_search_text_nonempty CHECK (length(text) > 0),
            CONSTRAINT ck_catalog_search_content_hash CHECK (
                content_hash ~ '^[0-9a-f]{64}$'
            )
        );

        CREATE INDEX idx_catalog_search_document_lexical
            ON catalog_search_document USING gin (search_vector);
        CREATE INDEX idx_catalog_search_document_neighbors
            ON catalog_search_document USING gin (neighbor_ids);
        CREATE INDEX idx_catalog_search_document_embedding
            ON catalog_search_document
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS catalog_search_document;")
