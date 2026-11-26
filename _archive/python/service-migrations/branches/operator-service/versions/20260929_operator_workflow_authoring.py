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
    """Create the audit table, grant required privileges, and guard Operator-written rows."""
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

        CREATE FUNCTION operator_workflow_definition_insert_guard() RETURNS trigger
        LANGUAGE plpgsql AS $guard$
        BEGIN
            IF current_user = 'fdai_operator' AND (
                NEW.origin <> 'user'
                OR NEW.visibility <> 'private'
                OR NEW.lifecycle <> 'draft'
                OR NEW.owner_ref IS NULL
                OR NEW.derived_from IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'operator workflow authoring may insert only private user drafts'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
        END;
        $guard$;
        REVOKE ALL ON FUNCTION operator_workflow_definition_insert_guard() FROM PUBLIC;
        CREATE TRIGGER operator_workflow_definition_insert_guard
            BEFORE INSERT ON workflow_definition
            FOR EACH ROW EXECUTE FUNCTION operator_workflow_definition_insert_guard();

        CREATE FUNCTION operator_workflow_binding_owner_guard() RETURNS trigger
        LANGUAGE plpgsql AS $guard$
        DECLARE
            definition_visibility TEXT;
            definition_owner TEXT;
        BEGIN
            IF current_user = 'fdai_operator' THEN
                SELECT visibility, owner_ref
                  INTO definition_visibility, definition_owner
                  FROM workflow_definition
                 WHERE definition_id = NEW.definition_id;
                IF definition_visibility = 'private'
                   AND definition_owner IS DISTINCT FROM NEW.principal_id THEN
                    RAISE EXCEPTION 'operator workflow binding must own its private definition'
                        USING ERRCODE = 'insufficient_privilege';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $guard$;
        REVOKE ALL ON FUNCTION operator_workflow_binding_owner_guard() FROM PUBLIC;
        CREATE TRIGGER operator_workflow_binding_owner_guard
            BEFORE INSERT OR UPDATE ON workflow_binding
            FOR EACH ROW EXECUTE FUNCTION operator_workflow_binding_owner_guard();
        """
    )


def downgrade() -> None:
    """Drop the audit ledger and return the Operator to the previous read-only grant."""
    op.execute(
        """
        DROP TRIGGER operator_workflow_binding_owner_guard ON workflow_binding;
        DROP FUNCTION operator_workflow_binding_owner_guard();
        DROP TRIGGER operator_workflow_definition_insert_guard ON workflow_definition;
        DROP FUNCTION operator_workflow_definition_insert_guard();
        REVOKE ALL PRIVILEGES ON TABLE workflow_definition, workflow_binding FROM fdai_operator;
        GRANT SELECT ON TABLE workflow_definition, workflow_binding TO fdai_operator;
        DROP TABLE operator_workflow_authoring_audit;
        """
    )
