"""install ontology direction guard for existing 0078 databases

Revision ID: 20260808_0079
Revises: 20260808_0078
Create Date: 2026-08-08 00:00:01+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260808_0079"
down_revision: str | None = "20260808_0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREVIOUS_RELEASE_DIGEST = "sha256:dd90ae7025bb0472cc091c23e8ed763f7d2ff94a109daf0295a60bb732f33037"


def upgrade() -> None:
    op.execute(
        f"""
        DELETE FROM ontology_link
        WHERE link_type = 'contains'
          AND (type_version = '1.0.0' OR type_version IS NULL);

        UPDATE ontology_resource
        SET type_version = NULL, catalog_digest = NULL
        WHERE catalog_digest = '{_PREVIOUS_RELEASE_DIGEST}';

        UPDATE ontology_link
        SET type_version = NULL, catalog_digest = NULL
        WHERE catalog_digest = '{_PREVIOUS_RELEASE_DIGEST}';

        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'ontology_link'::regclass
                  AND conname = 'ontology_link_contains_version_direction'
            ) THEN
                ALTER TABLE ontology_link
                ADD CONSTRAINT ontology_link_contains_version_direction
                CHECK (
                    link_type <> 'contains'
                    OR (type_version IS NOT NULL AND type_version <> '1.0.0')
                );
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE ontology_link
        DROP CONSTRAINT IF EXISTS ontology_link_contains_version_direction;
        """
    )
