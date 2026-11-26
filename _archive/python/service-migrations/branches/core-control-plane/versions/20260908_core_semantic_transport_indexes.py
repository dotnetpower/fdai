"""Add bounded semantic transport claim and replay indexes."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_semantic_transport_indexes_20260908"
down_revision: str | Sequence[str] | None = "core_oi16_synthetic_retention_20260907"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("state_kv",)
rollback = {
    "strategy": "drop-semantic-transport-indexes",
    "restores": "core_oi16_synthetic_retention_20260907",
    "requires": "none",
}


def upgrade() -> None:
    """Add concurrent indexes for Operator semantic claim and replay reads."""

    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS state_kv_operator_semantic_claim_idx")
        op.execute(
            "CREATE INDEX CONCURRENTLY "
            "state_kv_operator_semantic_claim_idx "
            "ON state_kv ("
            "(COALESCE(value ->> 'outbox_namespace', '')), "
            "(value ->> 'state'), "
            "(value ->> 'accepted_at'), "
            "key"
            ") WHERE value ->> 'kind' = 'operator.semantic_turn'"
        )
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS state_kv_operator_semantic_replay_idx")
        op.execute(
            "CREATE INDEX CONCURRENTLY "
            "state_kv_operator_semantic_replay_idx "
            "ON state_kv ("
            "(value ->> 'principal_id'), "
            "(value ->> 'request_id'), "
            "((value ->> 'event_sequence')::bigint)"
            ") WHERE key LIKE 'operator-semantic-result:%'"
        )


def downgrade() -> None:
    """Remove semantic transport indexes without blocking active writers."""

    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS state_kv_operator_semantic_replay_idx")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS state_kv_operator_semantic_claim_idx")
