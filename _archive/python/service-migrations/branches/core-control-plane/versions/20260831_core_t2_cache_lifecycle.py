"""Grant Core's runtime only the bounded T2 cache lifecycle operations."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_t2_cache_lifecycle_20260831"
down_revision: str | Sequence[str] | None = "core_cost_governance_settings_20260831"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "t2_cache_partition_registry",
    "t2_cache_catalog_state",
    "t2_cache_catalog_transition",
    "t2_cache_rotation_receipt",
)
rollback = {
    "strategy": "revoke-t2-cache-lifecycle-writes",
    "restores": "core_cost_governance_settings_20260831",
    "requires": "t2-cache-writer-stopped",
}


def upgrade() -> None:
    """Grant DML and bounded security-definer partition operations to Core."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            t2_cache_partition_registry,
            t2_cache_catalog_state,
            t2_cache_catalog_transition,
            t2_cache_rotation_receipt
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT, DELETE
            ON TABLE t2_cache_partition_registry TO fdai_core;
        GRANT SELECT, INSERT, UPDATE
            ON TABLE t2_cache_catalog_state TO fdai_core;
        GRANT SELECT, INSERT
            ON TABLE t2_cache_catalog_transition, t2_cache_rotation_receipt TO fdai_core;
        GRANT EXECUTE
            ON FUNCTION fdai_t2_cache_create_partition(TEXT),
                        fdai_t2_cache_drop_partition(TEXT)
            TO fdai_core;
        """
    )


def downgrade() -> None:
    """Revoke lifecycle writes without deleting cache state or receipts."""
    op.execute(
        """
        REVOKE EXECUTE
            ON FUNCTION fdai_t2_cache_create_partition(TEXT),
                        fdai_t2_cache_drop_partition(TEXT)
            FROM fdai_core;
        REVOKE ALL PRIVILEGES ON TABLE
            t2_cache_partition_registry,
            t2_cache_catalog_state,
            t2_cache_catalog_transition,
            t2_cache_rotation_receipt
        FROM fdai_core;
        """
    )
