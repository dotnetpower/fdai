"""separate publication claims from real publish failures

Revision ID: 20260723_0057
Revises: 20260723_0056
Create Date: 2026-07-23 16:40:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260723_0057"
down_revision: str | None = "20260723_0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE forecast_publication_outbox
            ADD COLUMN IF NOT EXISTS claim_count INTEGER NOT NULL DEFAULT 0
                CHECK (claim_count >= 0),
            ADD COLUMN IF NOT EXISTS publish_fail_count INTEGER NOT NULL DEFAULT 0
                CHECK (publish_fail_count >= 0);
        UPDATE forecast_publication_outbox
           SET claim_count = GREATEST(claim_count, attempts);
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE forecast_publication_outbox "
        "DROP COLUMN IF EXISTS publish_fail_count, DROP COLUMN IF EXISTS claim_count;"
    )
