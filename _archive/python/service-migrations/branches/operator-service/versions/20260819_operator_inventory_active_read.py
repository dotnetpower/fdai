"""Grant the Operator runtime read-only active inventory pointer access."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_inventory_active_read_20260819"
down_revision: str | Sequence[str] | None = "operator_incident_projection_read_20260819"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "revoke-operator-inventory-active-read",
    "restores": "operator_incident_projection_read_20260819",
    "requires": "operator-runtime-stopped",
}


def upgrade() -> None:
    """Expose only the active snapshot pointer to the Operator runtime role."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE inventory_active
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE inventory_active TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove active snapshot pointer access from the Operator role."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE inventory_active
        FROM fdai_operator
        """
    )
