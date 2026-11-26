"""Grant the Operator runtime read-only access to inventory activity history."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_activity_read_20260812"
down_revision: str | Sequence[str] | None = "operator_metering_read_20260810"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "revoke-operator-activity-read",
    "restores": "operator_metering_read_20260810",
    "requires": "operator-runtime-stopped",
}


def upgrade() -> None:
    """Grant SELECT only on the immutable inventory activity source tables."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            inventory_snapshot,
            inventory_snapshot_resource,
            inventory_snapshot_link
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE
            inventory_snapshot,
            inventory_snapshot_resource,
            inventory_snapshot_link
        TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove inventory activity projection access."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            inventory_snapshot,
            inventory_snapshot_resource,
            inventory_snapshot_link
        FROM fdai_operator
        """
    )
