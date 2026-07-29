"""inventory graph traversal indexes

Revision ID: 20260729_0061
Revises: 20260729_0060
Create Date: 2026-07-29 00:00:01+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260729_0061"
down_revision: str | None = "20260729_0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "idx_inventory_snapshot_link_reverse "
            "ON inventory_snapshot_link(snapshot_id, to_id, link_type, from_id)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "idx_inventory_realtime_link_reverse "
            "ON inventory_realtime_link(to_id, link_type, from_id)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_inventory_realtime_link_reverse")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_inventory_snapshot_link_reverse")
