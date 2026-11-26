-- Migration Revision: 20260708_0007
-- Down Revision: 20260706_0006
-- Owner: alembic
-- Extracted SQL Blocks: 2

-- Statement 1
CREATE TABLE IF NOT EXISTS action_idempotency (
            idempotency_key TEXT PRIMARY KEY
                CHECK (btrim(idempotency_key) <> ''),
            result          JSONB NOT NULL,
            recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        );

-- Statement 2
CREATE INDEX IF NOT EXISTS idx_action_idempotency_recorded_at
        ON action_idempotency (recorded_at DESC);
