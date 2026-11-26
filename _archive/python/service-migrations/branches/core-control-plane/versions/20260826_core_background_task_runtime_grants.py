"""Grant Core runtime access to its durable background-task tables."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_background_task_runtime_grants_20260826"
down_revision: str | Sequence[str] | None = "core_canonical_incident_projection_20260825"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "revoke-core-background-task-runtime-grants",
    "restores": "core_canonical_incident_projection_20260825",
    "requires": "core-runtime-stopped",
}


def upgrade() -> None:
    """Grant the durable coordinator its exact table privileges."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            background_task_attempt,
            background_task_progress,
            background_task_completion
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT, UPDATE, DELETE
            ON TABLE background_task_attempt TO fdai_core;
        GRANT SELECT, INSERT
            ON TABLE background_task_progress TO fdai_core;
        GRANT SELECT, INSERT, UPDATE
            ON TABLE background_task_completion TO fdai_core;
        """
    )


def downgrade() -> None:
    """Remove background-task access after the Core runtime is stopped."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            background_task_attempt,
            background_task_progress,
            background_task_completion
        FROM fdai_core
        """
    )
