"""Index recent Resource changes and exact ARG ingestion fences."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_recent_resource_changes_20260912"
down_revision: str | Sequence[str] | None = "core_runtime_call_snapshot_links_20260912"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("inventory_observation_journal",)
rollback = {
    "strategy": "drop-recent-resource-change-indexes",
    "restores": "core_runtime_call_snapshot_links_20260912",
    "requires": "none",
}


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY inventory_observation_recent_object_change_idx "
            "ON inventory_observation_journal "
            "(scope_ref, effective_at DESC, subject_ref, recorded_at DESC) "
            "INCLUDE (subject_type, operation, operation_status, mutation_kind, "
            "observation_kind, source_identity, observation_id, source_event_id, "
            "content_digest) WHERE subject_kind='object' "
            "AND ((source_identity='fdai.delivery.azure.arg_resource_changes' "
            "AND observation_kind IN ('full', 'tombstone')) "
            "OR (operation IS NOT NULL "
            "AND observation_kind IN ('partial', 'change_hint', 'tombstone')))"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY inventory_arg_change_event_fence_idx "
            "ON inventory_observation_journal (source_event_id) "
            "WHERE source_identity='fdai.delivery.azure.arg_resource_changes'"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS inventory_arg_change_event_fence_idx")
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS inventory_observation_recent_object_change_idx"
        )
