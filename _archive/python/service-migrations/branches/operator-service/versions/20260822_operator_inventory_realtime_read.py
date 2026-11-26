"""Grant the Operator runtime read-only realtime inventory overlay access."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_inventory_realtime_read_20260822"
down_revision: str | Sequence[str] | None = "operator_a3_channel_delivery_20260819"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "revoke-operator-inventory-realtime-read",
    "restores": "operator_a3_channel_delivery_20260819",
    "requires": "operator-runtime-stopped",
}


def upgrade() -> None:
    """Expose only realtime inventory overlay reads to the Operator role."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            inventory_realtime_resource,
            inventory_realtime_link
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE
            inventory_realtime_resource,
            inventory_realtime_link
        TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove realtime inventory overlay access from the Operator role."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            inventory_realtime_resource,
            inventory_realtime_link
        FROM fdai_operator
        """
    )
