-- Migration Revision: operator_workflow_authoring_20260929
-- Down Revision: operator_workflow_definition_read_20260929
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
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
