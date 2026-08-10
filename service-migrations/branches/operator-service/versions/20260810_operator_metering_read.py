"""Grant the Operator runtime read-only access to measured LLM usage."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_metering_read_20260810"
down_revision: str | Sequence[str] | None = "operator_runtime_role_20260808"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables = ("llm_invocation",)
rollback = {
    "strategy": "revoke-operator-metering-read",
    "restores": "operator_runtime_role_20260808",
    "requires": "operator-runtime-stopped",
}


def upgrade() -> None:
    """Grant only the SELECT privilege required by the usage projection."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE llm_invocation FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE llm_invocation TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove the metering projection's table access."""
    op.execute("REVOKE ALL PRIVILEGES ON TABLE llm_invocation FROM fdai_operator")
