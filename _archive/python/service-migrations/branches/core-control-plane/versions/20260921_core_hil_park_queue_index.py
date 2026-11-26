"""Keep active HIL queue reads independent from retained resolved parks."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_hil_park_queue_index_20260921"
down_revision: str | Sequence[str] | None = "core_inventory_progress_retention_20260921"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("state_kv",)
rollback = {
    "strategy": "drop-hil-park-queue-index",
    "restores": "core_inventory_progress_retention_20260921",
    "requires": "none",
}


def upgrade() -> None:
    """Index active HIL queue status and newest-first paging without blocking writers."""

    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS state_kv_hil_park_queue_idx "
            "ON state_kv ((value ->> 'status'), updated_at DESC, key DESC) "
            "WHERE key LIKE 'hil_park:%'"
        )


def downgrade() -> None:
    """Remove the HIL queue read index without changing retained authority records."""

    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS state_kv_hil_park_queue_idx")
