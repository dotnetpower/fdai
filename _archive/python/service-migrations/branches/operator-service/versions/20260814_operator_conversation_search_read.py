"""Grant the Operator runtime read-only access to conversation search sources."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_conversation_search_read_20260814"
down_revision: str | Sequence[str] | None = "operator_activity_read_20260812"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "revoke-operator-conversation-search-read",
    "restores": "operator_activity_read_20260812",
    "requires": "operator-runtime-stopped",
}


def upgrade() -> None:
    """Grant SELECT only on durable conversation records and turns."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            conversation_record,
            conversation_turn
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE
            conversation_record,
            conversation_turn
        TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove conversation search source access."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            conversation_record,
            conversation_turn
        FROM fdai_operator
        """
    )
