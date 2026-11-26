"""Optimize Core prefix reads and remove redundant query indexes."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "core_query_index_maintenance_20260825"
down_revision: str | Sequence[str] | None = "core_metering_sequence_20260825"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "catalog_search_generation_document",
    "question_campaign_attempt",
    "state_kv",
)
rollback = {
    "strategy": "restore-core-query-index-layout",
    "restores": "core_metering_sequence_20260825",
    "requires": "none",
}


def upgrade() -> None:
    """Add prefix support, reclaim empty catalog indexes, and drop one redundant index."""
    catalog_is_empty = bool(
        op.get_bind()
        .execute(
            sa.text("SELECT NOT EXISTS (SELECT 1 FROM catalog_search_generation_document LIMIT 1)")
        )
        .scalar_one()
    )
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_state_kv_key_prefix "
            "ON state_kv (key text_pattern_ops)"
        )
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_question_campaign_attempt_case")
        if catalog_is_empty:
            op.execute("REINDEX INDEX CONCURRENTLY catalog_search_generation_document_pkey")
            op.execute("REINDEX INDEX CONCURRENTLY idx_catalog_generation_document_lexical")
            op.execute("REINDEX INDEX CONCURRENTLY idx_catalog_generation_document_neighbors")
            op.execute("REINDEX INDEX CONCURRENTLY idx_catalog_generation_document_embedding")
            op.execute("REINDEX INDEX CONCURRENTLY uq_catalog_generation_document_ordinal")


def downgrade() -> None:
    """Restore the prior Core index layout without reversing reclaimed free space."""
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_state_kv_key_prefix")
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_question_campaign_attempt_case "
            "ON question_campaign_attempt(campaign_id, case_id, attempt_number DESC)"
        )
