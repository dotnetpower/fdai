"""Grant the Operator runtime read-only access to durable user-context sources."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_user_context_read_20260815"
down_revision: str | Sequence[str] | None = "operator_browser_evidence_read_20260815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "revoke-operator-user-context-read",
    "restores": "operator_browser_evidence_read_20260815",
    "requires": "operator-runtime-stopped",
}


def upgrade() -> None:
    """Grant SELECT only on the durable records the authenticated principal owns."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            user_preference,
            user_memory_fact,
            conversation_policy,
            briefing_subscription,
            briefing_run,
            scheduled_conversation_anchor
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE
            user_preference,
            user_memory_fact,
            conversation_policy,
            briefing_subscription,
            briefing_run,
            scheduled_conversation_anchor
        TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove durable user-context source access."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            user_preference,
            user_memory_fact,
            conversation_policy,
            briefing_subscription,
            briefing_run,
            scheduled_conversation_anchor
        FROM fdai_operator
        """
    )
