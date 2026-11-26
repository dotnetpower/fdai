-- Migration Revision: 20260717_0032
-- Down Revision: 20260717_0031
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE rpc_idempotency_claim (
            key_sha256 TEXT PRIMARY KEY CHECK (key_sha256 ~ '^[a-f0-9]{64}$'),
            state TEXT NOT NULL CHECK (state IN ('claimed', 'completed')),
            response JSONB,
            claimed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at TIMESTAMPTZ,
            CHECK (
                (state = 'claimed' AND response IS NULL AND completed_at IS NULL) OR
                (state = 'completed' AND jsonb_typeof(response) = 'object' AND
                 completed_at IS NOT NULL AND completed_at >= claimed_at)
            )
        );
