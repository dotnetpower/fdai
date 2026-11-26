-- Migration Revision: 20260720_0046
-- Down Revision: 20260720_0045
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE programmatic_pipeline_run (
            idempotency_key TEXT PRIMARY KEY,
            run_id TEXT NOT NULL UNIQUE,
            source_digest TEXT NOT NULL CHECK (char_length(source_digest) = 64),
            status TEXT NOT NULL CHECK (
                status IN (
                    'succeeded', 'rejected', 'failed',
                    'timed_out', 'cancelled', 'incomplete'
                )
            ),
            result JSONB NOT NULL CHECK (jsonb_typeof(result) = 'object'),
            completed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX programmatic_pipeline_run_completed_idx
            ON programmatic_pipeline_run (completed_at DESC, run_id);
        CREATE TABLE programmatic_pipeline_call (
            run_id TEXT NOT NULL,
            call_id TEXT NOT NULL,
            sequence INTEGER NOT NULL CHECK (sequence > 0),
            tool_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('succeeded', 'rejected', 'failed')),
            receipt JSONB NOT NULL CHECK (jsonb_typeof(receipt) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (run_id, call_id),
            UNIQUE (run_id, sequence)
        );
        CREATE INDEX programmatic_pipeline_call_tool_idx
            ON programmatic_pipeline_call (tool_id, recorded_at DESC);
