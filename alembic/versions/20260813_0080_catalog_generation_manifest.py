"""bind catalog generation rows to ordered document manifests

Revision ID: 20260813_0080
Revises: 20260808_0079
Create Date: 2026-08-13 00:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260813_0080"
down_revision: str | None = "20260808_0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM catalog_search_generation) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'catalog generation manifest migration requires ' ||
                        'an empty generation store',
                    HINT = 'Regenerate catalog generations through the ' ||
                        'manifest-aware lifecycle before retrying.';
            END IF;
        END
        $$;

        ALTER TABLE catalog_search_generation
            ADD COLUMN document_digest_root CHAR(71) NOT NULL,
            ADD COLUMN document_digest_chunks JSONB NOT NULL,
            ADD COLUMN inline_document_digests JSONB NOT NULL,
            ADD CONSTRAINT ck_catalog_generation_document_count_bound
                CHECK (document_count BETWEEN 1 AND 20000),
            ADD CONSTRAINT ck_catalog_generation_digest_root
                CHECK (document_digest_root ~ '^sha256:[0-9a-f]{64}$'),
            ADD CONSTRAINT ck_catalog_generation_digest_chunks
                CHECK (jsonb_typeof(document_digest_chunks) = 'array'
                       AND jsonb_array_length(document_digest_chunks) BETWEEN 1 AND 79
                       AND jsonb_array_length(document_digest_chunks)
                           = (document_count + 255) / 256),
            ADD CONSTRAINT ck_catalog_generation_inline_digests
                CHECK (jsonb_typeof(inline_document_digests) = 'array'
                       AND ((document_count <= 256
                             AND jsonb_array_length(inline_document_digests)
                                 = document_count)
                            OR (document_count > 256
                                AND inline_document_digests = '[]'::jsonb)));

        ALTER TABLE catalog_search_generation_document
            ADD COLUMN ordinal INTEGER NOT NULL,
            ADD COLUMN document_kind TEXT NOT NULL,
            ADD CONSTRAINT ck_catalog_generation_document_ordinal
                CHECK (ordinal BETWEEN 0 AND 19999),
            ADD CONSTRAINT ck_catalog_generation_document_kind
                CHECK (document_kind IN ('rule', 'ontology_declaration', 'ontology_object')),
            ADD CONSTRAINT uq_catalog_generation_document_ordinal
                UNIQUE (generation_id, ordinal);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM catalog_search_generation) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'catalog generation manifest downgrade requires ' ||
                        'an empty generation store',
                    HINT = 'Retain manifest-aware lifecycle history or explicitly ' ||
                        'remove generations before retrying.';
            END IF;
        END
        $$;

        ALTER TABLE catalog_search_generation_document
            DROP CONSTRAINT IF EXISTS uq_catalog_generation_document_ordinal,
            DROP CONSTRAINT IF EXISTS ck_catalog_generation_document_kind,
            DROP CONSTRAINT IF EXISTS ck_catalog_generation_document_ordinal,
            DROP COLUMN IF EXISTS document_kind,
            DROP COLUMN IF EXISTS ordinal;

        ALTER TABLE catalog_search_generation
            DROP CONSTRAINT IF EXISTS ck_catalog_generation_inline_digests,
            DROP CONSTRAINT IF EXISTS ck_catalog_generation_digest_chunks,
            DROP CONSTRAINT IF EXISTS ck_catalog_generation_digest_root,
            DROP CONSTRAINT IF EXISTS ck_catalog_generation_document_count_bound,
            DROP COLUMN IF EXISTS inline_document_digests,
            DROP COLUMN IF EXISTS document_digest_chunks,
            DROP COLUMN IF EXISTS document_digest_root;
        """
    )
