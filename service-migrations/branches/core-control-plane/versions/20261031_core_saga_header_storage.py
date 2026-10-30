"""Store immutable Saga headers beside audit payloads for bounded recovery."""

from __future__ import annotations

from alembic import op

revision = "core_saga_header_storage_20261031"
down_revision = "core_saga_compact_checkpoint_20261031"
branch_labels = None
depends_on = None

migration_owner = "core-control-plane"
owned_tables = ("audit_log",)
rollback = {
    "strategy": "drop-derived-header-after-reviewed-compatible-checkpoint-restore",
    "restores": "core_saga_compact_checkpoint_20261031",
}


def upgrade() -> None:
    op.execute(
        "SET LOCAL statement_timeout='15s'; SET LOCAL lock_timeout='2s'; "
        "ALTER TABLE audit_log ADD COLUMN saga_header JSONB GENERATED ALWAYS AS ("
        "CASE WHEN jsonb_exists_all(entry::jsonb,ARRAY['correlation_id','entry_hash',"
        "'payload_digest','prev_hash','principal','seq','topic']) "
        "OR (entry->>'actor'='Saga' AND entry->>'action_kind'='audit.record') THEN "
        "jsonb_set(jsonb_set(jsonb_set(jsonb_set(jsonb_set(jsonb_set(jsonb_set('{}'::jsonb,"
        "'{seq}',entry::jsonb->'seq'),'{prev_hash}',entry::jsonb->'prev_hash'),"
        "'{entry_hash}',entry::jsonb->'entry_hash'),'{principal}',entry::jsonb->'principal'),"
        "'{topic}',entry::jsonb->'topic'),'{correlation_id}',entry::jsonb->'correlation_id'),"
        "'{payload_digest}',entry::jsonb->'payload_digest') END) STORED"
    )
    with op.get_context().autocommit_block():
        op.execute("SET statement_timeout='15s'")
        op.execute("SET lock_timeout='2s'")
        try:
            op.execute(
                "CREATE INDEX CONCURRENTLY audit_log_saga_header_hash_idx "
                "ON audit_log ((saga_header->>'entry_hash')) WHERE saga_header IS NOT NULL"
            )
        finally:
            op.execute("RESET lock_timeout")
            op.execute("RESET statement_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET statement_timeout='15s'")
        op.execute("SET lock_timeout='2s'")
        try:
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS audit_log_saga_header_hash_idx")
        finally:
            op.execute("RESET lock_timeout")
            op.execute("RESET statement_timeout")
    op.execute(
        "SET LOCAL statement_timeout='15s'; SET LOCAL lock_timeout='2s'; "
        "ALTER TABLE audit_log DROP COLUMN saga_header"
    )
