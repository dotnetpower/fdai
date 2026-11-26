"""Index bounded complete histories without blocking the canonical audit writer."""

from alembic import op

revision = "core_canary_sequence_index_20261021"
down_revision = "core_document_intent_ingress_20261020"
branch_labels = None
depends_on = None
migration_owner = "core-control-plane"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "drop-rebuildable-canary-sequence-index",
    "restores": "core_document_intent_ingress_20261020",
    "requires": "none",
}


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS audit_log_canary_sequence_idx "
            "ON audit_log (event_id, correlation_id, seq) "
            "WHERE actor = 'fdai.canary-job' AND action_kind IN "
            "('control_loop.canary', 'control_loop.canary.attempt')"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS audit_log_canary_sequence_idx")
