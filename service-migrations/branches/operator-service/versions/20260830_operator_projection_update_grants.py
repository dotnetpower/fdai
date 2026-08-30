"""Grant updates required by Operator-owned projection upserts."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_projection_update_grants_20260830"
down_revision: str | Sequence[str] | None = "operator_background_task_projection_transport_20260829"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables = (
    "operator_read_investigation_completion",
    "operator_background_task_progress",
)
rollback = {
    "strategy": "stop-operator-projection-consumers-and-revoke-update",
    "restores": "operator_background_task_projection_transport_20260829",
    "requires": "operator-projection-consumers-stopped",
}


def upgrade() -> None:
    """Permit row locks only through each retention query's immutable key."""

    op.execute(
        """
        GRANT UPDATE (completion_id)
        ON TABLE operator_read_investigation_completion TO fdai_operator;
        GRANT UPDATE (task_id)
        ON TABLE operator_background_task_progress TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove projection updates after both consumers stop."""

    op.execute(
        """
        REVOKE UPDATE (completion_id)
        ON TABLE operator_read_investigation_completion FROM fdai_operator;
        REVOKE UPDATE (task_id)
        ON TABLE operator_background_task_progress FROM fdai_operator;
        """
    )
