"""Grant the Core Process writer the one sequence needed to append journal events."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_process_sequence_20260915"
down_revision: str | Sequence[str] | None = "core_cost_governance_review_20260913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("process_event",)
rollback = {
    "strategy": "revoke-process-sequence-usage",
    "restores": "core_cost_governance_review_20260913",
    "requires": "core-process-writers-stopped",
}


def upgrade() -> None:
    """Grant nextval only for Core's owned append path, never all schemas or peer roles."""
    op.execute("GRANT USAGE ON SEQUENCE process_event_seq_seq TO fdai_core")


def downgrade() -> None:
    """Restore prior grants after stopping Process writers; no journal data is removed."""
    op.execute("REVOKE USAGE ON SEQUENCE process_event_seq_seq FROM fdai_core")
