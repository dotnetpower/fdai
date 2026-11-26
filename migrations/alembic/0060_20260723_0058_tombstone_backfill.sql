-- Migration Revision: 20260723_0058
-- Down Revision: 20260723_0057
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
DO $$
        DECLARE constraint_name TEXT;
        BEGIN
            FOR constraint_name IN
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'case_history_revision'::regclass
                  AND contype = 'c'
                  AND pg_get_constraintdef(oid) LIKE '%artifact_size%'
            LOOP
                EXECUTE format(
                    'ALTER TABLE case_history_revision DROP CONSTRAINT %I',
                    constraint_name
                );
            END LOOP;
        END $$;
        ALTER TABLE case_history_revision
            ADD CONSTRAINT ck_case_history_revision_artifact_size
            CHECK (artifact_size >= 0);
