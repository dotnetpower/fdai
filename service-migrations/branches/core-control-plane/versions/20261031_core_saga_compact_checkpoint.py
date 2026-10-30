"""Index bounded canonical Saga ancestry reads for compact checkpoint recovery."""

from __future__ import annotations

from alembic import op

revision = "core_saga_compact_checkpoint_20261031"
down_revision = "core_state_storage_efficiency_20261030"
branch_labels = None
depends_on = None

migration_owner = "core-control-plane"
owned_tables = ("audit_log",)
rollback = {
    "strategy": "drop-saga-ancestry-index-before-reviewed-code-rollback",
    "restores": "core_state_storage_efficiency_20261030",
}


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET statement_timeout = '15s'")
        op.execute("SET lock_timeout = '2s'")
        try:
            op.execute(
                "CREATE INDEX CONCURRENTLY audit_log_saga_entry_hash_idx "
                "ON audit_log ((entry->>'entry_hash')) WHERE "
                "jsonb_exists_all(entry::jsonb,ARRAY['correlation_id','entry_hash',"
                "'payload_digest','prev_hash','principal','seq','topic']) "
                "OR (entry->>'actor'='Saga' AND entry->>'action_kind'='audit.record')"
            )
        finally:
            op.execute("RESET lock_timeout")
            op.execute("RESET statement_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET statement_timeout = '15s'")
        op.execute("SET lock_timeout = '2s'")
        try:
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS audit_log_saga_entry_hash_idx")
        finally:
            op.execute("RESET lock_timeout")
            op.execute("RESET statement_timeout")
