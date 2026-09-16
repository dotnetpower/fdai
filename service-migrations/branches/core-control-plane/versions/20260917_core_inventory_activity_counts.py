"""Persist exact inventory snapshot counts for bounded activity reads."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_inventory_activity_counts_20260917"
down_revision: str | Sequence[str] | None = "core_inventory_temporal_axes_20260916"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("inventory_snapshot",)
rollback = {
    "strategy": "drop-inventory-activity-counts",
    "restores": "core_inventory_temporal_axes_20260916",
    "requires": "core-and-operator-runtimes-stopped",
}


def upgrade() -> None:
    """Backfill exact terminal snapshot counts without changing source evidence."""

    op.execute(
        """
        ALTER TABLE inventory_snapshot
            ADD COLUMN resource_count BIGINT,
            ADD COLUMN link_count BIGINT;

        ALTER TABLE inventory_snapshot
            ADD CONSTRAINT ck_inventory_snapshot_resource_count_nonnegative
                CHECK (resource_count IS NULL OR resource_count >= 0),
            ADD CONSTRAINT ck_inventory_snapshot_link_count_nonnegative
                CHECK (link_count IS NULL OR link_count >= 0);

        WITH counts AS (
            SELECT snapshot_id, COUNT(*) AS value
              FROM inventory_snapshot_resource
             GROUP BY snapshot_id
        )
        UPDATE inventory_snapshot AS snapshot
           SET resource_count = counts.value
          FROM counts
         WHERE snapshot.id = counts.snapshot_id
           AND snapshot.status IN ('active', 'superseded');

        UPDATE inventory_snapshot
           SET resource_count = 0
         WHERE status IN ('active', 'superseded')
           AND resource_count IS NULL;

        WITH counts AS (
            SELECT snapshot_id, COUNT(*) AS value
              FROM inventory_snapshot_link
             GROUP BY snapshot_id
        )
        UPDATE inventory_snapshot AS snapshot
           SET link_count = counts.value
          FROM counts
         WHERE snapshot.id = counts.snapshot_id
           AND snapshot.status IN ('active', 'superseded');

        UPDATE inventory_snapshot
           SET link_count = 0
         WHERE status IN ('active', 'superseded')
           AND link_count IS NULL;
        """
    )


def downgrade() -> None:
    """Remove only the additive activity summary columns."""

    op.execute(
        """
        ALTER TABLE inventory_snapshot
            DROP CONSTRAINT ck_inventory_snapshot_link_count_nonnegative,
            DROP CONSTRAINT ck_inventory_snapshot_resource_count_nonnegative,
            DROP COLUMN link_count,
            DROP COLUMN resource_count;
        """
    )
