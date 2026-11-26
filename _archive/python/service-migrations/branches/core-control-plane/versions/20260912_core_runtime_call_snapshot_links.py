"""Allow verified runtime-call links in Core inventory projections."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_runtime_call_snapshot_links_20260912"
down_revision: str | Sequence[str] | None = "core_post_release_closure_20260912"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("inventory_realtime_link", "inventory_snapshot_link")
rollback = {
    "strategy": "delete-rebuildable-runtime-call-links-and-restore-constraints",
    "restores": "core_post_release_closure_20260912",
    "requires": "inventory-writers-stopped",
}


def upgrade() -> None:
    """Expand current snapshot and real-time constraints for runtime calls."""

    op.execute(
        """
        ALTER TABLE inventory_snapshot_link
            DROP CONSTRAINT inventory_snapshot_link_link_type_check;
        ALTER TABLE inventory_snapshot_link
            ADD CONSTRAINT inventory_snapshot_link_link_type_check
            CHECK (link_type IN (
                'contains', 'attached_to', 'depends_on', 'peered_with', 'routes_to',
                'kubernetes_scheduled_on', 'kubernetes_backed_by',
                'kubernetes_owned_by', 'kubernetes_selects',
                'kubernetes_exposes_endpoints', 'kubernetes_exposes_endpoint_slice',
                'runtime_calls'
            ));
        ALTER TABLE inventory_realtime_link
            DROP CONSTRAINT inventory_realtime_link_link_type_check;
        ALTER TABLE inventory_realtime_link
            ADD CONSTRAINT inventory_realtime_link_link_type_check
            CHECK (link_type IN (
                'contains', 'attached_to', 'depends_on', 'peered_with', 'routes_to',
                'kubernetes_scheduled_on', 'kubernetes_backed_by',
                'kubernetes_owned_by', 'kubernetes_selects',
                'kubernetes_exposes_endpoints', 'kubernetes_exposes_endpoint_slice',
                'runtime_calls'
            ));
        """
    )


def downgrade() -> None:
    """Delete rebuildable runtime-call links before restoring prior constraints."""

    op.execute(
        """
        DELETE FROM inventory_realtime_link WHERE link_type = 'runtime_calls';
        DELETE FROM inventory_snapshot_link WHERE link_type = 'runtime_calls';
        ALTER TABLE inventory_realtime_link
            DROP CONSTRAINT inventory_realtime_link_link_type_check;
        ALTER TABLE inventory_realtime_link
            ADD CONSTRAINT inventory_realtime_link_link_type_check
            CHECK (link_type IN (
                'contains', 'attached_to', 'depends_on', 'peered_with', 'routes_to',
                'kubernetes_scheduled_on', 'kubernetes_backed_by',
                'kubernetes_owned_by', 'kubernetes_selects',
                'kubernetes_exposes_endpoints', 'kubernetes_exposes_endpoint_slice'
            ));
        ALTER TABLE inventory_snapshot_link
            DROP CONSTRAINT inventory_snapshot_link_link_type_check;
        ALTER TABLE inventory_snapshot_link
            ADD CONSTRAINT inventory_snapshot_link_link_type_check
            CHECK (link_type IN (
                'contains', 'attached_to', 'depends_on', 'peered_with', 'routes_to',
                'kubernetes_scheduled_on', 'kubernetes_backed_by',
                'kubernetes_owned_by', 'kubernetes_selects',
                'kubernetes_exposes_endpoints', 'kubernetes_exposes_endpoint_slice'
            ));
        """
    )
