"""Cover semantic claim filtering and ordering in one bounded index."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_semantic_transport_ordering_20260908"
down_revision: str | Sequence[str] | None = "core_semantic_transport_indexes_20260908"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("state_kv",)
rollback = {
    "strategy": "drop-semantic-claim-ordering-index",
    "restores": "core_semantic_transport_indexes_20260908",
    "requires": "none",
}


def upgrade() -> None:
    """Add a concurrent covering index for ordered claim reads."""

    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS state_kv_operator_semantic_claim_order_idx")
        op.execute(
            "CREATE INDEX CONCURRENTLY "
            "state_kv_operator_semantic_claim_order_idx "
            "ON state_kv ("
            "(COALESCE(value ->> 'outbox_namespace', '')), "
            "(value ->> 'accepted_at'), "
            "key"
            ") WHERE value ->> 'kind' = 'operator.semantic_turn' "
            "AND (value ->> 'state' = 'pending' OR value ->> 'state' = 'claimed')"
        )


def downgrade() -> None:
    """Remove the semantic claim ordering index without blocking writers."""

    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS state_kv_operator_semantic_claim_order_idx")
