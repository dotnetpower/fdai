-- Migration Revision: 20260720_0039
-- Down Revision: 20260720_0038
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE task_worker_run (
            worker_id TEXT PRIMARY KEY,
            parent_trace_ref TEXT NOT NULL,
            cancellation_owner TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN (
                'pending', 'running', 'succeeded', 'abstained', 'cancelled',
                'timed_out', 'budget_exhausted', 'denied', 'failed'
            )),
            request JSONB NOT NULL,
            capabilities JSONB NOT NULL,
            usage JSONB NOT NULL,
            result JSONB,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            heartbeat_at TIMESTAMPTZ,
            revision BIGINT NOT NULL DEFAULT 1 CHECK (revision >= 1),
            CHECK (
                (status IN ('pending', 'running') AND result IS NULL)
                OR (status NOT IN ('pending', 'running') AND result IS NOT NULL)
            )
        );
        CREATE INDEX ix_task_worker_run_parent
            ON task_worker_run (parent_trace_ref, updated_at DESC);
        CREATE INDEX ix_task_worker_run_owner
            ON task_worker_run (cancellation_owner, updated_at DESC, worker_id DESC);
        CREATE INDEX ix_task_worker_run_status
            ON task_worker_run (status, updated_at DESC);

        CREATE TABLE task_worker_event (
            worker_id TEXT NOT NULL REFERENCES task_worker_run(worker_id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL CHECK (sequence >= 0),
            kind TEXT NOT NULL,
            at TIMESTAMPTZ NOT NULL,
            details JSONB NOT NULL DEFAULT '[]'::jsonb,
            PRIMARY KEY (worker_id, sequence)
        );
