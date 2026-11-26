-- Migration Revision: 20260912_0090
-- Down Revision: 20260831_0089
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
ALTER TABLE skill_proposal
        ADD COLUMN IF NOT EXISTS evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(evidence_refs) = 'array');
