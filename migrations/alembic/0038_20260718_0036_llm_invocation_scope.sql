-- Migration Revision: 20260718_0036
-- Down Revision: 20260718_0035
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
ALTER TABLE llm_invocation
            ADD COLUMN usage_scope TEXT NOT NULL DEFAULT 'control_plane'
            CHECK (usage_scope IN ('control_plane', 'operator_chat'));
