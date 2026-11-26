-- Migration Revision: 20260720_0042
-- Down Revision: 20260720_0041
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
ALTER TABLE trusted_artifact
            DROP CONSTRAINT trusted_artifact_artifact_kind_check;
        ALTER TABLE trusted_artifact
            ADD CONSTRAINT trusted_artifact_artifact_kind_check
            CHECK (artifact_kind IN ('extension', 'skill', 'skill_bundle'));
