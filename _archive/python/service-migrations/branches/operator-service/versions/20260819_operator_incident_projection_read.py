"""Grant the Operator runtime read-only incident projection access."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_incident_projection_read_20260819"
down_revision: str | Sequence[str] | None = "operator_user_context_read_20260815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "revoke-operator-incident-projection-read",
    "restores": "operator_user_context_read_20260815",
    "requires": "operator-runtime-stopped",
}


def upgrade() -> None:
    """Expose only the temporal incident roster projection to the runtime role."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE operator_incident_projection
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE operator_incident_projection TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove temporal incident projection access from the Operator role."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE operator_incident_projection
        FROM fdai_operator
        """
    )
