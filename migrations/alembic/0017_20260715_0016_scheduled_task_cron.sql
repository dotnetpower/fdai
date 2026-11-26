-- Migration Revision: 20260715_0016
-- Down Revision: 20260714_0015
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
ALTER TABLE scheduled_task ADD COLUMN IF NOT EXISTS cron_expression TEXT;
