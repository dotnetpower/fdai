"""persist ontology LinkType traversal semantics

Revision ID: 20260729_0060
Revises: 20260725_0059
Create Date: 2026-07-29 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260729_0060"
down_revision: str | None = "20260725_0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ontology_link_type "
        "ADD COLUMN IF NOT EXISTS is_transitive BOOLEAN NOT NULL DEFAULT FALSE, "
        "ADD COLUMN IF NOT EXISTS is_causal BOOLEAN NOT NULL DEFAULT FALSE, "
        "ADD COLUMN IF NOT EXISTS temporal_order BOOLEAN NOT NULL DEFAULT FALSE, "
        "ADD COLUMN IF NOT EXISTS order_by_property TEXT;"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE ontology_link_type "
        "DROP COLUMN IF EXISTS order_by_property, "
        "DROP COLUMN IF EXISTS temporal_order, "
        "DROP COLUMN IF EXISTS is_causal, "
        "DROP COLUMN IF EXISTS is_transitive;"
    )
