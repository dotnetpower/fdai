-- Migration Revision: 20260715_0017
-- Down Revision: 20260715_0016
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE IF NOT EXISTS python_task_artifact (
            artifact_ref TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            version TEXT NOT NULL,
            artifact_hash TEXT NOT NULL CHECK (artifact_hash ~ '^[0-9a-f]{64}$'),
            manifest JSONB NOT NULL,
            created_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (task_id, version)
        );
