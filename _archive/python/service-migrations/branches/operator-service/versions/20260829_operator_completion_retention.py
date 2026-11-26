"""Grant the Operator bounded read-investigation completion retention cleanup."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_completion_retention_20260829"
down_revision: str | Sequence[str] | None = "operator_cost_governance_20260828"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables = ("operator_read_investigation_completion",)
rollback = {
    "strategy": "stop-completion-retention-and-revoke-delete",
    "restores": "operator_cost_governance_20260828",
    "requires": "operator-completion-retention-stopped",
}


def upgrade() -> None:
    """Permit only the Operator runtime to purge its expired completion inbox rows."""

    op.execute(
        """
        REVOKE DELETE ON TABLE operator_read_investigation_completion
        FROM PUBLIC;
        GRANT DELETE ON TABLE operator_read_investigation_completion
        TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove completion cleanup permission after the retention worker stops."""

    op.execute(
        """
        REVOKE DELETE ON TABLE operator_read_investigation_completion
        FROM fdai_operator;
        """
    )
