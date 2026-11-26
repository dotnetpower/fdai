-- Migration Revision: 20260713_0014
-- Down Revision: 20260713_0013
-- Owner: alembic
-- Extracted SQL Blocks: 3

-- Statement 1
CREATE TABLE IF NOT EXISTS process_projection_outbox (
            event_id      TEXT PRIMARY KEY REFERENCES process_event(event_id) ON DELETE CASCADE,
            process_id    TEXT NOT NULL REFERENCES process_runtime(process_id) ON DELETE CASCADE,
            attempts      INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            available_at  TIMESTAMPTZ NOT NULL,
            leased_until  TIMESTAMPTZ,
            last_error    TEXT
        );

-- Statement 2
INSERT INTO process_projection_outbox (event_id, process_id, available_at)
        SELECT event_id, process_id, recorded_at FROM process_event
        ON CONFLICT (event_id) DO NOTHING;

-- Statement 3
CREATE INDEX IF NOT EXISTS idx_process_projection_outbox_available ON process_projection_outbox(available_at, event_id);
