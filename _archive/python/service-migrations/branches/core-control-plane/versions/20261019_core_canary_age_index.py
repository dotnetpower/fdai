"""Index latest consumed canary success without blocking active audit writers."""

from alembic import op

revision = "core_canary_age_index_20261019"
down_revision = "core_code_security_claim_renewal_20261010"
branch_labels = None
depends_on = None
migration_owner = "core-control-plane"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "drop-rebuildable-canary-age-index",
    "restores": "core_code_security_claim_renewal_20261010",
    "requires": "none",
}


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS audit_log_canary_success_latest_idx "
            "ON audit_log (seq DESC) "
            "WHERE action_kind = 'control_loop.canary' AND actor = 'fdai.canary-job' "
            "AND entry ->> 'outcome' = 'success'"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS audit_log_canary_success_latest_idx")
