"""ontology instances: optimistic revisions and idempotent links

Revision ID: 20260713_0011
Revises: 20260712_0010
Create Date: 2026-07-13 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260713_0011"
down_revision: str | None = "20260712_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ontology_resource "
        "ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 1 "
        "CHECK (revision >= 1);"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ontology_link_identity "
        "ON ontology_link(from_id, link_type, to_id);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_ontology_link_identity;")
    op.execute("ALTER TABLE ontology_resource DROP COLUMN IF EXISTS revision;")
