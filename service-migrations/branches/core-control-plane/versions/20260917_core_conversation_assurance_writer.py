"""Grant Core append-only access to conversation assurance evidence."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_conversation_assurance_writer_20260917"
down_revision: str | Sequence[str] | None = "core_cost_governance_live_20260917"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "revoke-core-conversation-assurance-writes",
    "restores": "core_cost_governance_live_20260917",
    "requires": "core-runtime-stopped",
}


def upgrade() -> None:
    """Grant only the reads and append writes used by the Core assessment ledger."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            conversation_assurance_assessment,
            conversation_assurance_dispute
        FROM fdai_core;
        GRANT SELECT, INSERT ON TABLE
            conversation_assurance_assessment,
            conversation_assurance_dispute
        TO fdai_core;
        """
    )


def downgrade() -> None:
    """Remove only Core access to the Operator-migrated assurance tables."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            conversation_assurance_assessment,
            conversation_assurance_dispute
        FROM fdai_core
        """
    )
