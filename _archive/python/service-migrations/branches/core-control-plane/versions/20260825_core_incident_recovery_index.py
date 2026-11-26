"""Index incident lifecycle recovery without blocking active audit writers."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_incident_recovery_index_20260825"
down_revision: str | Sequence[str] | None = "core_metering_writer_20260825"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "drop-rebuildable-incident-recovery-index",
    "restores": "core_metering_writer_20260825",
    "requires": "none",
}


def upgrade() -> None:
    """Create the partial recovery index while active audit writers continue."""
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS audit_log_incident_recovery_idx "
            "ON audit_log (action_kind, seq) "
            "WHERE action_kind IN ("
            "'incident.open', 'incident.members', 'incident.severity', "
            "'incident.assigned', 'incident.ticket', 'incident.transition'"
            ")"
        )


def downgrade() -> None:
    """Drop the rebuildable recovery index without blocking active audit writers."""
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS audit_log_incident_recovery_idx")
