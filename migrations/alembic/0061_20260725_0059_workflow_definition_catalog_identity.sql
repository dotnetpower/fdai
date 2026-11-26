-- Migration Revision: 20260725_0059
-- Down Revision: 20260723_0058
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
DO $$
        DECLARE constraint_name TEXT;
        BEGIN
            LOCK TABLE workflow_definition IN ACCESS EXCLUSIVE MODE;

            SELECT conname INTO constraint_name
            FROM pg_constraint
            WHERE conrelid = 'workflow_definition'::regclass
              AND contype = 'u'
              AND pg_get_constraintdef(oid) =
                  'UNIQUE (workflow_name, workflow_version, definition_hash)';
            IF constraint_name IS NOT NULL THEN
                EXECUTE format(
                    'ALTER TABLE workflow_definition DROP CONSTRAINT %I',
                    constraint_name
                );
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'workflow_definition'::regclass
                  AND conname = 'uq_workflow_definition_catalog_identity'
            ) THEN
                ALTER TABLE workflow_definition
                    ADD CONSTRAINT uq_workflow_definition_catalog_identity
                    UNIQUE (
                        workflow_name,
                        workflow_version,
                        definition_hash,
                        action_catalog_digest
                    );
            END IF;
        END $$;
