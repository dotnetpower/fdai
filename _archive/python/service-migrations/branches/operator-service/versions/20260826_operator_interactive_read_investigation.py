"""Grant Operator owner-scoped interactive read projection access."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_interactive_read_investigation_20260826"
down_revision: str | Sequence[str] | None = "operator_read_investigation_completion_20260826"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "revoke-operator-interactive-read-investigation-read",
    "restores": "operator_read_investigation_completion_20260826",
    "requires": "operator-runtime-stopped",
}


def upgrade() -> None:
    """Grant projection reads without any Core state transition authority."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            read_investigation_run,
            read_investigation_run_progress,
            read_investigation_run_completion
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE
            read_investigation_run,
            read_investigation_run_progress,
            read_investigation_run_completion
        TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove only the Operator projection reads."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            read_investigation_run,
            read_investigation_run_progress,
            read_investigation_run_completion
        FROM fdai_operator
        """
    )
