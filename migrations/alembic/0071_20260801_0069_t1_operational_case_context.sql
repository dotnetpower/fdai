-- Migration Revision: 20260801_0069
-- Down Revision: 20260801_0068
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
ALTER TABLE t1_pattern_library
            ADD COLUMN operational_case JSONB,
            ADD CONSTRAINT ck_t1_pattern_operational_case_object CHECK (
                operational_case IS NULL OR jsonb_typeof(operational_case) = 'object'
            );
