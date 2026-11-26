-- Migration Revision: 20260713_0012
-- Down Revision: 20260713_0011
-- Owner: alembic
-- Extracted SQL Blocks: 4

-- Statement 1
CREATE TABLE IF NOT EXISTS process_runtime (
            process_id         TEXT PRIMARY KEY,
            workflow_ref       TEXT NOT NULL,
            workflow_version   TEXT NOT NULL,
            status             TEXT NOT NULL CHECK (status IN (
                'pending','running','waiting','compensating','compensated',
                'succeeded','failed','cancelled','timed_out'
            )),
            current_step       TEXT NOT NULL DEFAULT '',
            target_resource_id TEXT NOT NULL,
            started_at         TIMESTAMPTZ NOT NULL,
            updated_at         TIMESTAMPTZ NOT NULL,
            correlation_id     TEXT NOT NULL,
            revision           BIGINT NOT NULL DEFAULT 1 CHECK (revision >= 1)
        );

-- Statement 2
CREATE TABLE IF NOT EXISTS process_event (
            seq             BIGSERIAL PRIMARY KEY,
            event_id        TEXT NOT NULL UNIQUE,
            process_id      TEXT NOT NULL REFERENCES process_runtime(process_id) ON DELETE CASCADE,
            kind            TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            recorded_at     TIMESTAMPTZ NOT NULL,
            correlation_id  TEXT NOT NULL,
            causation_id    TEXT,
            step_id         TEXT,
            attempt         INTEGER NOT NULL CHECK (attempt >= 1),
            payload         JSONB NOT NULL DEFAULT '{}'::jsonb
        );

-- Statement 3
CREATE INDEX IF NOT EXISTS idx_process_event_process_seq ON process_event(process_id, seq);

-- Statement 4
CREATE INDEX IF NOT EXISTS idx_process_runtime_workflow_status ON process_runtime(workflow_ref, status);
