"""Grant Core ownership of durable interactive read-investigation state."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_interactive_read_investigation_20260826"
down_revision: str | Sequence[str] | None = "core_background_task_runtime_grants_20260826"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "read_investigation_run",
    "read_investigation_run_progress",
    "read_investigation_run_completion",
)
rollback = {
    "strategy": "revoke-core-interactive-read-investigation",
    "restores": "core_background_task_runtime_grants_20260826",
    "requires": "core-runtime-stopped",
}


def upgrade() -> None:
    """Grant only the writes owned by the interactive coordinator."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            read_investigation_run,
            read_investigation_run_progress,
            read_investigation_run_completion
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT, UPDATE, DELETE
            ON TABLE read_investigation_run TO fdai_core;
        GRANT SELECT, INSERT
            ON TABLE read_investigation_run_progress TO fdai_core;
        GRANT SELECT, INSERT, UPDATE
            ON TABLE read_investigation_run_completion TO fdai_core;
        """
    )


def downgrade() -> None:
    """Remove interactive writes only after the Core runtime stops."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            read_investigation_run,
            read_investigation_run_progress,
            read_investigation_run_completion
        FROM fdai_core
        """
    )
