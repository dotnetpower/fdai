"""Grant Operator read-only access to durable runtime projection tables."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_runtime_projection_reads_20260827"
down_revision: str | Sequence[str] | None = "operator_interactive_read_investigation_20260826"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "revoke-operator-runtime-projection-reads",
    "restores": "operator_interactive_read_investigation_20260826",
    "requires": "operator-runtime-stopped",
}


def upgrade() -> None:
    """Grant only SELECT on Process and automation blueprint records."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            process_runtime,
            process_event,
            automation_blueprint_candidate
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE
            process_runtime,
            process_event,
            automation_blueprint_candidate
        TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove only the durable runtime projection reads."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            process_runtime,
            process_event,
            automation_blueprint_candidate
        FROM fdai_operator
        """
    )
