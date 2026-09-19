"""Index bounded inventory source-coverage checks by active scope."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_inventory_coverage_indexes_20260919"
down_revision: str | Sequence[str] | None = "core_knowledge_read_20260917"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "inventory_observation_journal",
    "inventory_observation_partition",
)
rollback = {
    "strategy": "drop-inventory-source-coverage-indexes",
    "restores": "core_knowledge_read_20260917",
    "requires": "none",
}


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY inventory_observation_journal_scope_watermark_idx "
            "ON inventory_observation_journal (scope_ref, watermark) "
            "INCLUDE (source_revision, effective_at)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY inventory_correction_pending_scope_watermark_idx "
            "ON inventory_observation_partition (scope_ref, last_watermark) "
            "WHERE state='correction_pending'"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY inventory_correction_pending_scope_watermark_idx")
        op.execute("DROP INDEX CONCURRENTLY inventory_observation_journal_scope_watermark_idx")
