"""Tune tracked-state vacuum and index principal-scoped conversation summaries."""

from __future__ import annotations

from alembic import op

revision = "core_state_storage_efficiency_20261030"
down_revision = "core_inventory_storage_efficiency_20261030"
branch_labels = None
depends_on = None

migration_owner = "core-control-plane"
owned_tables = ("state_kv",)
rollback = {
    "strategy": "drop-summary-index-and-reset-state-vacuum-settings",
    "restores": "core_inventory_storage_efficiency_20261030",
}


def upgrade() -> None:
    op.execute(
        "SET LOCAL statement_timeout = '15s'; SET LOCAL lock_timeout = '2s'; "
        "ALTER TABLE state_kv SET (autovacuum_vacuum_scale_factor=0.01, "
        "autovacuum_vacuum_threshold=1000, toast.autovacuum_vacuum_scale_factor=0.01, "
        "toast.autovacuum_vacuum_threshold=1000)"
    )
    with op.get_context().autocommit_block():
        op.execute("SET statement_timeout = '15s'")
        op.execute("SET lock_timeout = '2s'")
        try:
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS state_kv_conversation_summary_idx")
            op.execute(
                "CREATE INDEX CONCURRENTLY state_kv_conversation_summary_idx "
                "ON state_kv ((value ->> 'principal_id'), "
                "(value #>> '{envelope,semantic_turn,session_id}'), "
                "(value ->> 'accepted_at'), key) "
                "WHERE value ->> 'kind' = 'operator.semantic_turn'"
            )
        finally:
            op.execute("RESET lock_timeout")
            op.execute("RESET statement_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET statement_timeout = '15s'")
        op.execute("SET lock_timeout = '2s'")
        try:
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS state_kv_conversation_summary_idx")
        finally:
            op.execute("RESET lock_timeout")
            op.execute("RESET statement_timeout")
    op.execute(
        "SET LOCAL statement_timeout = '15s'; SET LOCAL lock_timeout = '2s'; "
        "ALTER TABLE state_kv RESET (autovacuum_vacuum_scale_factor, "
        "autovacuum_vacuum_threshold, toast.autovacuum_vacuum_scale_factor, "
        "toast.autovacuum_vacuum_threshold)"
    )
