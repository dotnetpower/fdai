"""Grant the Operator runtime read-only background-task projection access."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_background_task_read_20260823"
down_revision: str | Sequence[str] | None = "operator_inventory_realtime_read_20260822"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "revoke-operator-background-task-read",
    "restores": "operator_inventory_realtime_read_20260822",
    "requires": "operator-runtime-stopped",
}


def upgrade() -> None:
    """Expose only owner-filtered background-task source reads to Operator."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            background_task_attempt,
            background_task_progress,
            background_task_completion
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE
            background_task_attempt,
            background_task_progress,
            background_task_completion
        TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove background-task source access from the Operator role."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            background_task_attempt,
            background_task_progress,
            background_task_completion
        FROM fdai_operator
        """
    )
