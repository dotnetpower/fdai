"""Persist lifecycle collection completeness and gap state with the cursor."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_kubernetes_lifecycle_completeness_20260829"
down_revision: str | Sequence[str] | None = "core_catalog_lifecycle_20260829"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("kubernetes_lifecycle_cursor",)
rollback = {
    "strategy": "drop-kubernetes-lifecycle-completeness-columns",
    "restores": "core_kubernetes_lifecycle_20260828",
    "requires": "kubernetes-lifecycle-collector-stopped",
}


def upgrade() -> None:
    """Add the atomic collection health fields used by durable readers."""

    op.execute(
        """
        ALTER TABLE kubernetes_lifecycle_cursor
            ALTER COLUMN resource_version DROP NOT NULL;
        ALTER TABLE kubernetes_lifecycle_cursor
            ADD COLUMN complete BOOLEAN NOT NULL DEFAULT TRUE,
            ADD COLUMN limitation TEXT NULL;
        """
    )


def downgrade() -> None:
    """Remove collection health fields after lifecycle consumers stop."""

    op.execute(
        """
        DELETE FROM kubernetes_lifecycle_cursor WHERE resource_version IS NULL;
        ALTER TABLE kubernetes_lifecycle_cursor
            DROP COLUMN limitation,
            DROP COLUMN complete;
        ALTER TABLE kubernetes_lifecycle_cursor
            ALTER COLUMN resource_version SET NOT NULL;
        """
    )
