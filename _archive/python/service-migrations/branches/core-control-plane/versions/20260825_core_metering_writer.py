"""Grant Core append-only access to the Operator-owned LLM metering ledger."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_metering_writer_20260825"
down_revision: str | Sequence[str] | None = "core_operational_archive_20260822"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("llm_invocation",)
rollback = {
    "strategy": "revoke-core-metering-writer",
    "restores": "core_operational_archive_20260822",
    "requires": "core-runtime-stopped",
}


def upgrade() -> None:
    """Grant only the read and append privileges required by Core metering."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE llm_invocation FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT ON TABLE llm_invocation TO fdai_core;
        """
    )


def downgrade() -> None:
    """Remove Core access after the metering producer is stopped."""
    op.execute("REVOKE ALL PRIVILEGES ON TABLE llm_invocation FROM fdai_core")
