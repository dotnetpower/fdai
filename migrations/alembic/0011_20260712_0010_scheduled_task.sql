-- Migration Revision: 20260712_0010
-- Down Revision: 20260712_0009
-- Owner: alembic
-- Extracted SQL Blocks: 2

-- Statement 1
CREATE TABLE IF NOT EXISTS scheduled_task (
            task_id          TEXT PRIMARY KEY,
            name             TEXT NOT NULL,
            interval_seconds DOUBLE PRECISION NOT NULL CHECK (interval_seconds > 0),
            event_type       TEXT NOT NULL,
            created_by       TEXT NOT NULL,
            event_payload    JSONB NOT NULL DEFAULT '{}'::jsonb,
            resource_ref     TEXT,
            enabled          BOOLEAN NOT NULL DEFAULT TRUE,
            start_at         TIMESTAMPTZ,
            last_run         TIMESTAMPTZ,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

-- Statement 2
CREATE INDEX idx_scheduled_task_enabled ON scheduled_task(enabled) WHERE enabled;
