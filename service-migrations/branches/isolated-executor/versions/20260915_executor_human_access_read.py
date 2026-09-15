"""Grant the isolated Executor only exact immutable human-access source readback."""

from alembic import op

revision = "executor_human_access_read_20260915"
down_revision = "executor_safeguard_bundle_read_20260912"
branch_labels = None
depends_on = None
migration_owner = "isolated-executor"
owned_tables: tuple[str, ...] = ()
migration_prerequisites = {
    "service": "core-control-plane",
    "revision": "core_human_access_execution_20260915",
}
rollback = {
    "strategy": "revoke-exact-human-access-read",
    "restores": "executor_safeguard_bundle_read_20260912",
    "requires": "isolated-executor-effect-consumer-stopped",
}


def upgrade() -> None:
    """No assignment write grant or arbitrary private query is added."""
    op.execute(
        "GRANT EXECUTE ON FUNCTION fdai_executor_human_access_source(text, text) TO fdai_executor"
    )


def downgrade() -> None:
    """Remove only this read capability after the isolated consumer stops."""
    op.execute(
        "REVOKE EXECUTE ON FUNCTION fdai_executor_human_access_source(text, text) "
        "FROM fdai_executor"
    )
