"""Grant the Operator runtime read-only access to durable workflow definitions and bindings."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_workflow_definition_read_20260929"
down_revision: str | Sequence[str] | None = "operator_rule_activation_receipts_20260922"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ("workflow_binding", "workflow_definition")
rollback = {
    "strategy": "revoke-operator-workflow-definition-read",
    "restores": "operator_rule_activation_receipts_20260922",
    "requires": "operator-runtime-stopped",
}


def upgrade() -> None:
    """Grant SELECT only; the catalog reader filters every row to the requesting principal."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE workflow_definition, workflow_binding
            FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE workflow_definition, workflow_binding TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove the Operator's workflow definition and binding read access."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE workflow_definition, workflow_binding
            FROM fdai_operator
        """
    )
