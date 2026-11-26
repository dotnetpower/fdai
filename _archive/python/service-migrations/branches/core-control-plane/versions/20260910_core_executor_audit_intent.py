"""Create the executor pre-effect audit-intent table."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_executor_audit_intent_20260910"
down_revision: str | Sequence[str] | None = "core_executor_idempotency_reservation_20260910"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("executor_audit_intent",)
rollback = {
    "strategy": "drop-executor-audit-intent",
    "restores": "core_executor_idempotency_reservation_20260910",
    "requires": "executor-audit-intent-writers-stopped",
}


def upgrade() -> None:
    """Create the exact-readback pre-effect intent store."""

    op.execute(
        """
        CREATE TABLE executor_audit_intent (
            intent_key TEXT PRIMARY KEY
                CHECK (intent_key ~ '^sha256:[0-9a-f]{64}$'),
            intent_digest TEXT NOT NULL
                CHECK (intent_digest ~ '^sha256:[0-9a-f]{64}$'),
            record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
        );

        REVOKE ALL PRIVILEGES ON TABLE executor_audit_intent
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT ON TABLE executor_audit_intent TO fdai_core;
        """
    )


def downgrade() -> None:
    """Drop pre-effect intents after all executor writers stop."""

    op.execute("DROP TABLE executor_audit_intent")
