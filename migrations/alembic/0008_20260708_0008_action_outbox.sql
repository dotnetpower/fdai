-- Migration Revision: 20260708_0008
-- Down Revision: 20260708_0007
-- Owner: alembic
-- Extracted SQL Blocks: 3

-- Statement 1
CREATE TABLE IF NOT EXISTS action_outbox (
            idempotency_key TEXT PRIMARY KEY
                CHECK (btrim(idempotency_key) <> ''),
            status          TEXT NOT NULL
                CHECK (status IN ('in_progress', 'done')),
            result          JSONB NULL,
            claimed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at    TIMESTAMPTZ NULL,
            CONSTRAINT action_outbox_done_has_result
                CHECK (status <> 'done' OR result IS NOT NULL),
            CONSTRAINT action_outbox_done_has_completed_at
                CHECK (status <> 'done' OR completed_at IS NOT NULL)
        );

-- Statement 2
CREATE INDEX IF NOT EXISTS idx_action_outbox_claimed_at
        ON action_outbox (claimed_at DESC);

-- Statement 3
CREATE INDEX IF NOT EXISTS idx_action_outbox_status
        ON action_outbox (status);
