"""Create the target-wide executor dispatch fence table."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_target_dispatch_fence_20260910"
down_revision: str | Sequence[str] | None = "core_executor_audit_intent_20260910"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("target_dispatch_fence",)
rollback = {
    "strategy": "drop-target-dispatch-fence",
    "restores": "core_executor_audit_intent_20260910",
    "requires": "executor-dispatch-fence-writers-stopped",
}


def upgrade() -> None:
    """Create one authoritative current generation per target."""

    op.execute(
        """
        CREATE TABLE target_dispatch_fence (
            target_digest TEXT PRIMARY KEY
                CHECK (target_digest ~ '^sha256:[0-9a-f]{64}$'),
            generation INTEGER NOT NULL CHECK (generation > 0),
            revision INTEGER NOT NULL CHECK (revision > 0),
            state TEXT NOT NULL CHECK (
                state IN (
                    'preparing',
                    'prepared',
                    'in_flight',
                    'release_pending',
                    'resolved',
                    'quarantined'
                )
            ),
            identity_digest TEXT NOT NULL
                CHECK (identity_digest ~ '^sha256:[0-9a-f]{64}$'),
            record_digest TEXT NOT NULL
                CHECK (record_digest ~ '^sha256:[0-9a-f]{64}$'),
            record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
        );

        REVOKE ALL PRIVILEGES ON TABLE target_dispatch_fence
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT, UPDATE ON TABLE target_dispatch_fence TO fdai_core;
        """
    )


def downgrade() -> None:
    """Drop target fences after every executor writer stops."""

    op.execute("DROP TABLE target_dispatch_fence")
