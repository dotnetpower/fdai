"""Grant Core sequence access for the append-only LLM metering ledger."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_metering_sequence_20260825"
down_revision: str | Sequence[str] | None = "core_incident_recovery_index_20260825"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "revoke-core-metering-sequence",
    "restores": "core_incident_recovery_index_20260825",
    "requires": "core-runtime-stopped",
}


def upgrade() -> None:
    """Grant only the sequence privileges required to append metering rows."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON SEQUENCE llm_invocation_invocation_id_seq
            FROM PUBLIC, fdai_core;
        GRANT USAGE, SELECT ON SEQUENCE llm_invocation_invocation_id_seq TO fdai_core;
        """
    )


def downgrade() -> None:
    """Remove Core sequence access after the metering producer is stopped."""
    op.execute("REVOKE ALL PRIVILEGES ON SEQUENCE llm_invocation_invocation_id_seq FROM fdai_core")
