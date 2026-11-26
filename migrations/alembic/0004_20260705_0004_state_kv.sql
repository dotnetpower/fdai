-- Migration Revision: 20260705_0004
-- Down Revision: 20260705_0003
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE IF NOT EXISTS state_kv (
            key         TEXT PRIMARY KEY,
            value       JSONB NOT NULL,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
