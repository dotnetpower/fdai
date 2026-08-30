"""Index selective ontology property containment queries."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_ontology_property_index_20260830"
down_revision: str | Sequence[str] | None = "core_ontology_endpoint_integrity_20260830"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("ontology_resource",)
rollback = {
    "strategy": "drop-ontology-properties-gin-index",
    "restores": "core_ontology_endpoint_integrity_20260830",
}


def upgrade() -> None:
    """Accelerate the existing JSONB containment query shape."""

    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_ontology_resource_properties_gin")
        op.execute(
            "CREATE INDEX CONCURRENTLY idx_ontology_resource_properties_gin "
            "ON ontology_resource USING GIN (properties jsonb_path_ops)"
        )


def downgrade() -> None:
    """Remove the optional containment index."""

    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_ontology_resource_properties_gin")
