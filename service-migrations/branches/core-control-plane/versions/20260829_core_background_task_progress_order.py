"""Grant Core runtime access for the background-task projection transport."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_background_task_progress_order_20260829"
down_revision: str | Sequence[str] | None = "core_standing_authority_lifecycle_20260829"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "revoke-core-background-task-projection-transport",
    "restores": "core_standing_authority_lifecycle_20260829",
    "requires": "core-runtime-stopped",
}


def upgrade() -> None:
    """Grant only the outbox and sequence privileges required by the Core publisher."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE background_task_projection_outbox
            FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT, UPDATE ON TABLE background_task_projection_outbox TO fdai_core;

        REVOKE ALL PRIVILEGES ON SEQUENCE background_task_progress_append_order_seq
            FROM PUBLIC, fdai_core;
        GRANT USAGE, SELECT ON SEQUENCE background_task_progress_append_order_seq TO fdai_core;

        REVOKE ALL PRIVILEGES ON SEQUENCE
            background_task_projection_outbox_outbox_sequence_seq
        FROM PUBLIC, fdai_core;
        GRANT USAGE, SELECT ON SEQUENCE
            background_task_projection_outbox_outbox_sequence_seq
        TO fdai_core;
        """
    )


def downgrade() -> None:
    """Remove Core projection transport access after the publisher is stopped."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE background_task_projection_outbox FROM fdai_core;
        REVOKE ALL PRIVILEGES ON SEQUENCE background_task_progress_append_order_seq
        FROM fdai_core;
        REVOKE ALL PRIVILEGES ON SEQUENCE
            background_task_projection_outbox_outbox_sequence_seq
        FROM fdai_core
        """
    )
