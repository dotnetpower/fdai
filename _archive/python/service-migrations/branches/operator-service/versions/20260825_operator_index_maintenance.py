"""Remove Operator indexes duplicated by ordered unique constraints."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_index_maintenance_20260825"
down_revision: str | Sequence[str] | None = "operator_background_task_read_20260823"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables = (
    "conversation_outbound_delivery_attempt",
    "conversation_turn",
)
rollback = {
    "strategy": "restore-operator-query-index-layout",
    "restores": "operator_background_task_read_20260823",
    "requires": "none",
}


def upgrade() -> None:
    """Drop indexes whose ordered scans are covered by unique constraint indexes."""
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS conversation_outbound_delivery_attempt_delivery_idx"
        )
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_conversation_turn_history")


def downgrade() -> None:
    """Restore the prior Operator index layout without blocking active writers."""
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "conversation_outbound_delivery_attempt_delivery_idx "
            "ON conversation_outbound_delivery_attempt (delivery_id, sequence DESC)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_conversation_turn_history "
            "ON conversation_turn (principal_id, conversation_id, turn_index)"
        )
