"""persist exact ontology release manifests

Revision ID: 20260813_0081
Revises: 20260813_0080
Create Date: 2026-08-13 00:00:01+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260813_0081"
down_revision: str | None = "20260813_0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ontology_release (
            digest TEXT PRIMARY KEY,
            manifest JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_ontology_release_digest
                CHECK (digest ~ '^sha256:[0-9a-f]{64}$'),
            CONSTRAINT ck_ontology_release_manifest_object
                CHECK (jsonb_typeof(manifest) = 'object'),
            CONSTRAINT ck_ontology_release_manifest_digest
                CHECK (manifest ->> 'digest' = digest),
            CONSTRAINT ck_ontology_release_declarations_array
                CHECK (jsonb_typeof(manifest -> 'declarations') = 'array')
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE ontology_release")
