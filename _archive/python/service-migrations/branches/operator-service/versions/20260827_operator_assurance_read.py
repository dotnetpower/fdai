"""Grant Operator read-only access to conversation assurance evidence."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_assurance_read_20260827"
down_revision: str | Sequence[str] | None = "operator_runtime_projection_reads_20260827"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "revoke-operator-assurance-read",
    "restores": "operator_runtime_projection_reads_20260827",
    "requires": "operator-runtime-stopped",
}


def upgrade() -> None:
    """Grant only SELECT on assurance assessments and disputes."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            conversation_assurance_assessment,
            conversation_assurance_dispute
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE
            conversation_assurance_assessment,
            conversation_assurance_dispute
        TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove only the conversation assurance projection reads."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            conversation_assurance_assessment,
            conversation_assurance_dispute
        FROM fdai_operator
        """
    )
