"""add atomic catalog semantic generations

Revision ID: 20260806_0077
Revises: 20260806_0076
Create Date: 2026-08-06 20:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260806_0077"
down_revision: str | None = "20260806_0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE catalog_search_generation (
            generation_id TEXT PRIMARY KEY,
            generation_digest CHAR(71) NOT NULL,
            corpus TEXT NOT NULL,
            catalog_digest CHAR(71) NOT NULL,
            semantic_schema_digest CHAR(71) NOT NULL,
            ontology_release_digest CHAR(71) NOT NULL,
            embedding_space_id TEXT NOT NULL,
            embedding_model_version TEXT NOT NULL,
            embedding_dimension INTEGER NOT NULL,
            state TEXT NOT NULL,
            validation_receipt_digest CHAR(71),
            document_count INTEGER NOT NULL,
            activated_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_catalog_generation_corpus
                CHECK (corpus IN ('active', 'discovery')),
            CONSTRAINT ck_catalog_generation_state
                CHECK (state IN ('staged', 'active', 'retired', 'failed')),
            CONSTRAINT ck_catalog_generation_dimension
                CHECK (embedding_dimension > 0),
            CONSTRAINT ck_catalog_generation_document_count
                CHECK (document_count > 0),
            CONSTRAINT ck_catalog_generation_activation
                CHECK ((state <> 'active') OR
                       (activated_at IS NOT NULL AND validation_receipt_digest IS NOT NULL))
        );

        CREATE UNIQUE INDEX uq_catalog_generation_active_corpus
            ON catalog_search_generation (corpus)
            WHERE state = 'active';

        CREATE TABLE catalog_search_generation_document (
            generation_id TEXT NOT NULL REFERENCES catalog_search_generation(generation_id)
                ON DELETE CASCADE,
            rule_id TEXT NOT NULL,
            text TEXT NOT NULL,
            neighbor_ids TEXT[] NOT NULL,
            search_vector TSVECTOR NOT NULL,
            embedding vector(384) NOT NULL,
            manifest_digest CHAR(71),
            surface_digest CHAR(71),
            content_hash CHAR(64) NOT NULL,
            PRIMARY KEY (generation_id, rule_id),
            CONSTRAINT ck_catalog_generation_rule_id_nonempty CHECK (length(rule_id) > 0),
            CONSTRAINT ck_catalog_generation_text_nonempty CHECK (length(text) > 0)
        );

        CREATE INDEX idx_catalog_generation_document_lexical
            ON catalog_search_generation_document USING gin (search_vector);
        CREATE INDEX idx_catalog_generation_document_neighbors
            ON catalog_search_generation_document USING gin (neighbor_ids);
        CREATE INDEX idx_catalog_generation_document_embedding
            ON catalog_search_generation_document
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS catalog_search_generation_document;
        DROP TABLE IF EXISTS catalog_search_generation;
        """
    )
