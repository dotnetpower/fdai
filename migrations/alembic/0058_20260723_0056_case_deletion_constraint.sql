-- Migration Revision: 20260723_0056
-- Down Revision: 20260723_0055
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
DO $$
        DECLARE constraint_name TEXT;
        BEGIN
            FOR constraint_name IN
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'case_history'::regclass
                  AND contype = 'c'
                  AND pg_get_constraintdef(oid) LIKE '%deletion_storage_refs%'
                  AND pg_get_constraintdef(oid) LIKE '%deletion_started_at%'
            LOOP
                EXECUTE format(
                    'ALTER TABLE case_history DROP CONSTRAINT %I', constraint_name
                );
            END LOOP;
        END $$;
        ALTER TABLE case_history
            ADD CONSTRAINT ck_case_history_safe_deletion_refs CHECK (
                (deletion_started_at IS NULL AND cardinality(deletion_storage_refs) = 0)
                OR (deletion_started_at IS NOT NULL
                    AND deleted_at IS NULL
                    AND cardinality(deletion_storage_refs) > 0
                    AND array_position(deletion_storage_refs, '') IS NULL
                    AND array_to_string(deletion_storage_refs, ',') ~
                        '^case-history/[A-Za-z0-9._/-]+(,case-history/[A-Za-z0-9._/-]+)*$')
                OR (deletion_started_at IS NOT NULL
                    AND deleted_at IS NOT NULL
                    AND cardinality(deletion_storage_refs) = 0)
            );
