"""Allow observed VNet peering links in Core-owned inventory snapshots."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_inventory_peered_links_20260810"
down_revision: str | Sequence[str] | None = "core_runtime_role_20260809"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("inventory_snapshot_link",)
rollback = {
    "strategy": "delete-rebuildable-peering-links-and-restore-constraint",
    "restores": "core_runtime_role_20260809",
    "requires": "inventory-refresh-stopped",
}


def upgrade() -> None:
    """Expand the bounded inventory relationship vocabulary for VNet peering."""
    op.execute(
        """
        ALTER TABLE inventory_snapshot_link
            DROP CONSTRAINT inventory_snapshot_link_link_type_check;
        ALTER TABLE inventory_snapshot_link
            ADD CONSTRAINT inventory_snapshot_link_link_type_check
            CHECK (link_type IN ('contains', 'attached_to', 'depends_on', 'peered_with'));
        """
    )


def downgrade() -> None:
    """Remove rebuildable peering rows before restoring the prior constraint."""
    op.execute(
        """
        DELETE FROM inventory_snapshot_link WHERE link_type = 'peered_with';
        ALTER TABLE inventory_snapshot_link
            DROP CONSTRAINT inventory_snapshot_link_link_type_check;
        ALTER TABLE inventory_snapshot_link
            ADD CONSTRAINT inventory_snapshot_link_link_type_check
            CHECK (link_type IN ('contains', 'attached_to', 'depends_on'));
        """
    )
