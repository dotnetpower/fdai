"""Merge Kubernetes topology and lifecycle migration heads."""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "core_kubernetes_merge_20260827"
down_revision: str | Sequence[str] | None = (
    "core_kubernetes_inventory_links_20260826",
    "core_kubernetes_lifecycle_20260827",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "remove-kubernetes-migration-merge-marker",
    "restores": "core_kubernetes_inventory_links_20260826,core_kubernetes_lifecycle_20260827",
    "requires": "none",
}


def upgrade() -> None:
    """Join two independently validated Kubernetes migration branches."""


def downgrade() -> None:
    """Remove only the merge marker while preserving both parent revisions."""
