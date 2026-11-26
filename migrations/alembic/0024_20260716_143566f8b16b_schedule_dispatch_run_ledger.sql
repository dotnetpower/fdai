-- Migration Revision: 143566f8b16b
-- Down Revision: 20260716_0022
-- Owner: alembic
-- Extracted SQL Blocks: 3

-- Statement 1
CREATE TABLE schedule_dispatch_run (
            run_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES scheduled_task(task_id) ON DELETE CASCADE,
            scheduled_for TIMESTAMPTZ NOT NULL,
            claimed_at TIMESTAMPTZ NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('claimed', 'published', 'failed', 'lost')),
            attempt INTEGER NOT NULL CHECK (attempt >= 1),
            completed_at TIMESTAMPTZ,
            error_kind TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

-- Statement 2
CREATE INDEX idx_schedule_dispatch_run_task_time ON schedule_dispatch_run(task_id, scheduled_for DESC);

-- Statement 3
CREATE INDEX idx_schedule_dispatch_run_claimed ON schedule_dispatch_run(claimed_at) WHERE status = 'claimed';
