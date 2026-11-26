"""Create the executor idempotency reservation table."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_executor_idempotency_reservation_20260910"
down_revision: str | Sequence[str] | None = "core_kubernetes_lifecycle_coverage_20260910"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("executor_idempotency_reservation",)
rollback = {
    "strategy": "drop-executor-idempotency-reservation",
    "restores": "core_kubernetes_lifecycle_coverage_20260910",
    "requires": "executor-reservation-writers-stopped",
}


def upgrade() -> None:
    """Create the exact-record executor reservation store."""

    op.execute(
        """
        CREATE TABLE executor_idempotency_reservation (
            idempotency_key TEXT PRIMARY KEY
                CHECK (char_length(idempotency_key) BETWEEN 1 AND 533),
            result JSONB NOT NULL CHECK (jsonb_typeof(result) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
        );

        REVOKE ALL PRIVILEGES ON TABLE executor_idempotency_reservation
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT, UPDATE
            ON TABLE executor_idempotency_reservation TO fdai_core;
        """
    )


def downgrade() -> None:
    """Drop the reservation store after all executor writers stop."""

    op.execute("DROP TABLE executor_idempotency_reservation")
