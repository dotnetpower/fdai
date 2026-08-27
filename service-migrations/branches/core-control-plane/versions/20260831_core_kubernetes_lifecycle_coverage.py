"""Persist resumable Kubernetes LIST progress and continuous coverage."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_kubernetes_lifecycle_coverage_20260831"
down_revision: str | Sequence[str] | None = "core_kubernetes_pod_lifecycle_identity_20260830"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("kubernetes_lifecycle_cursor",)
rollback = {
    "strategy": "drop-kubernetes-lifecycle-coverage-columns",
    "restores": "core_kubernetes_pod_lifecycle_identity_20260830",
    "requires": "kubernetes-lifecycle-collector-stopped",
}


def upgrade() -> None:
    """Add private LIST continuation and continuous coverage boundaries."""

    op.execute(
        """
        ALTER TABLE kubernetes_lifecycle_cursor
            ADD COLUMN list_continue_token TEXT NULL
                CHECK (
                    list_continue_token IS NULL
                    OR char_length(list_continue_token) BETWEEN 1 AND 2048
                ),
            ADD COLUMN coverage_started_at TIMESTAMPTZ NULL,
            ADD CONSTRAINT kubernetes_lifecycle_cursor_phase_check
                CHECK (
                    resource_version IS NULL
                    OR list_continue_token IS NULL
                ),
            ADD CONSTRAINT kubernetes_lifecycle_cursor_coverage_check
                CHECK (
                    coverage_started_at IS NULL
                    OR coverage_started_at <= updated_at
                );
        """
    )


def downgrade() -> None:
    """Remove lifecycle coverage fields after consumers stop."""

    op.execute(
        """
        ALTER TABLE kubernetes_lifecycle_cursor
            DROP CONSTRAINT kubernetes_lifecycle_cursor_coverage_check,
            DROP CONSTRAINT kubernetes_lifecycle_cursor_phase_check,
            DROP COLUMN coverage_started_at,
            DROP COLUMN list_continue_token;
        """
    )
