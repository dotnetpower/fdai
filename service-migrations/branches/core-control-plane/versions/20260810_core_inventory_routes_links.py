"""Allow observed routing and peering links in Core inventory projections."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_inventory_routes_links_20260810"
down_revision: str | Sequence[str] | None = "core_topology_history_20260810"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("inventory_realtime_link", "inventory_snapshot_link")
rollback = {
    "strategy": "delete-rebuildable-routing-links-and-restore-constraints",
    "restores": "core_topology_history_20260810",
    "requires": "inventory-writers-stopped",
}


def upgrade() -> None:
    """Expand current snapshot and real-time relationship constraints."""
    op.execute(
        """
        ALTER TABLE inventory_snapshot_link
            DROP CONSTRAINT inventory_snapshot_link_link_type_check;
        ALTER TABLE inventory_snapshot_link
            ADD CONSTRAINT inventory_snapshot_link_link_type_check
            CHECK (link_type IN
                ('contains', 'attached_to', 'depends_on', 'peered_with', 'routes_to'));
        ALTER TABLE inventory_realtime_link
            DROP CONSTRAINT inventory_realtime_link_link_type_check;
        ALTER TABLE inventory_realtime_link
            ADD CONSTRAINT inventory_realtime_link_link_type_check
            CHECK (link_type IN
                ('contains', 'attached_to', 'depends_on', 'peered_with', 'routes_to'));
        """
    )


def downgrade() -> None:
    """Remove rebuildable links before restoring prior constraints."""
    op.execute(
        """
        DELETE FROM inventory_realtime_link
            WHERE link_type IN ('peered_with', 'routes_to');
        DELETE FROM inventory_snapshot_link WHERE link_type = 'routes_to';
        ALTER TABLE inventory_realtime_link
            DROP CONSTRAINT inventory_realtime_link_link_type_check;
        ALTER TABLE inventory_realtime_link
            ADD CONSTRAINT inventory_realtime_link_link_type_check
            CHECK (link_type IN ('contains', 'attached_to', 'depends_on'));
        ALTER TABLE inventory_snapshot_link
            DROP CONSTRAINT inventory_snapshot_link_link_type_check;
        ALTER TABLE inventory_snapshot_link
            ADD CONSTRAINT inventory_snapshot_link_link_type_check
            CHECK (link_type IN ('contains', 'attached_to', 'depends_on', 'peered_with'));
        """
    )
