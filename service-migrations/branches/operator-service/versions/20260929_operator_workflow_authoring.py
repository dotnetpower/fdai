"""Grant bounded Operator workflow authoring and retain an audit ledger."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_workflow_authoring_20260929"
down_revision: str | Sequence[str] | None = "operator_workflow_definition_read_20260929"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = (
    "operator_workflow_authoring_audit",
    "workflow_binding",
    "workflow_definition",
)
rollback = {
    "strategy": "drop-operator-workflow-authoring-audit-and-restore-read-grant",
    "restores": "operator_workflow_definition_read_20260929",
    "requires": "operator-runtime-stopped",
}


def upgrade() -> None:
    """Create the Operator audit table and grant only required table privileges."""
    op.execute(
        """
        CREATE TABLE operator_workflow_authoring_audit (
            audit_id BIGSERIAL PRIMARY KEY,
            principal_id TEXT NOT NULL,
            operation TEXT NOT NULL CHECK (
                operation IN (
                    'workflow-definition.create',
                    'workflow-binding.create',
                    'workflow-binding.update',
                    'workflow-binding.delete'
                )
            ),
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            result JSONB NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (principal_id, operation, idempotency_key)
        );
        REVOKE ALL PRIVILEGES ON TABLE operator_workflow_authoring_audit FROM PUBLIC, fdai_operator;
        REVOKE ALL PRIVILEGES ON SEQUENCE operator_workflow_authoring_audit_audit_id_seq
            FROM PUBLIC, fdai_operator;
        GRANT SELECT, INSERT ON TABLE operator_workflow_authoring_audit TO fdai_operator;
        GRANT USAGE, SELECT ON SEQUENCE operator_workflow_authoring_audit_audit_id_seq
            TO fdai_operator;

        REVOKE ALL PRIVILEGES ON TABLE workflow_definition, workflow_binding
            FROM PUBLIC, fdai_operator;
        GRANT SELECT, INSERT ON TABLE workflow_definition TO fdai_operator;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE workflow_binding TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Drop the audit ledger and return the Operator to the previous read-only grant."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE workflow_definition, workflow_binding FROM fdai_operator;
        GRANT SELECT ON TABLE workflow_definition, workflow_binding TO fdai_operator;
        DROP TABLE operator_workflow_authoring_audit;
        """
    )
