"""Join the independently authored alert Process and human-access migration heads."""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "core_alert_handover_merge_20260915"
down_revision: str | Sequence[str] | None = (
    "core_process_sequence_20260915",
    "core_human_access_execution_20260915",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "remove-alert-handover-merge-marker",
    "restores": "core_process_sequence_20260915,core_human_access_execution_20260915",
    "requires": "none",
}


def upgrade() -> None:
    """Retain both parent migrations without changing data, grants or applied revision history."""


def downgrade() -> None:
    """Remove only this merge marker; both parent revisions and their effects remain."""
