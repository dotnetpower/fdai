"""Restore the root-owned T2 cache lookup index after service lifecycle rollback."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_t2_cache_lookup_repair_20260906"
down_revision: str | Sequence[str] | None = "core_operational_history_lifecycle_20260906"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("t2_cache",)
rollback = {
    "strategy": "preserve-root-owned-t2-cache-lookup-index",
    "restores": "core_operational_history_lifecycle_20260906",
    "requires": "core-runtime-stopped",
}


def upgrade() -> None:
    """Converge the service branch on the current root cache index contract."""

    op.execute(
        """
        DROP INDEX IF EXISTS idx_t2_cache_expires_at;
        CREATE INDEX IF NOT EXISTS idx_t2_cache_lookup
            ON t2_cache (catalog_version, input_hash, expires_at DESC, created_at DESC);
        """
    )


def downgrade() -> None:
    """Preserve the lookup index because the legacy root owns it."""
