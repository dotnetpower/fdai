-- Migration Revision: 20260814_0084
-- Down Revision: 20260814_0083
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
DROP INDEX trajectory_dataset_retention_idx;
        ALTER TABLE trajectory_dataset
            DROP CONSTRAINT trajectory_dataset_state_check,
            ADD CONSTRAINT ck_trajectory_dataset_state CHECK (
                state IN (
                    'pending', 'completed', 'cancelled', 'quarantined', 'deleting', 'deleted'
                )
            ),
            ADD CONSTRAINT ck_trajectory_deleting_claim CHECK (
                state <> 'deleting'
                OR (
                    legal_hold = FALSE
                    AND storage_ref IS NOT NULL
                    AND dataset_checksum IS NOT NULL
                    AND manifest_checksum IS NOT NULL
                )
            );
        CREATE INDEX trajectory_dataset_retention_idx
            ON trajectory_dataset (deletion_due_at, dataset_id)
            WHERE state IN ('completed', 'deleting') AND legal_hold = FALSE;
