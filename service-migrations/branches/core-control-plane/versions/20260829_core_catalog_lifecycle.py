"""Add catalog-version and expiry columns to Core lookup persistence."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_catalog_lifecycle_20260829"
down_revision: str | Sequence[str] | None = "core_kubernetes_lifecycle_20260828"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "learned_action",
    "t2_cache",
)
rollback = {
    "strategy": "drop-catalog-lifecycle-columns",
    "restores": "core_kubernetes_lifecycle_20260828",
    "requires": "core-runtime-stopped",
}


def upgrade() -> None:
    """Make learned actions version-scoped and T2 entries expirable."""
    op.execute(
        """
        ALTER TABLE learned_action
            ADD COLUMN IF NOT EXISTS catalog_version TEXT;
        UPDATE learned_action
           SET catalog_version = 'legacy'
         WHERE catalog_version IS NULL;
        ALTER TABLE learned_action
            ALTER COLUMN catalog_version SET NOT NULL,
            ALTER COLUMN catalog_version SET DEFAULT 'legacy';
        CREATE INDEX IF NOT EXISTS idx_learned_action_rule_catalog
            ON learned_action (rule_id, catalog_version);

        ALTER TABLE t2_cache
            ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
        UPDATE t2_cache
           SET expires_at = created_at + INTERVAL '1 hour'
         WHERE expires_at IS NULL;
        ALTER TABLE t2_cache
            ALTER COLUMN expires_at SET NOT NULL,
            ALTER COLUMN expires_at SET DEFAULT (NOW() + INTERVAL '1 hour');
        CREATE INDEX IF NOT EXISTS idx_t2_cache_expires_at
            ON t2_cache (expires_at);
        """
    )


def downgrade() -> None:
    """Remove only the lifecycle columns added by this service revision."""
    op.execute(
        """
        DROP INDEX IF EXISTS idx_t2_cache_expires_at;
        ALTER TABLE t2_cache
            DROP COLUMN IF EXISTS expires_at;
        DROP INDEX IF EXISTS idx_learned_action_rule_catalog;
        ALTER TABLE learned_action
            DROP COLUMN IF EXISTS catalog_version;
        """
    )
