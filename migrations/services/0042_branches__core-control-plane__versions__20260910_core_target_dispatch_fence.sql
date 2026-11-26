-- Migration Revision: core_target_dispatch_fence_20260910
-- Down Revision: core_executor_audit_intent_20260910
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE target_dispatch_fence (
            target_digest TEXT PRIMARY KEY
                CHECK (target_digest ~ '^sha256:[0-9a-f]{64}$'),
            generation INTEGER NOT NULL CHECK (generation > 0),
            revision INTEGER NOT NULL CHECK (revision > 0),
            state TEXT NOT NULL CHECK (
                state IN (
                    'preparing',
                    'prepared',
                    'in_flight',
                    'release_pending',
                    'resolved',
                    'quarantined'
                )
            ),
            identity_digest TEXT NOT NULL
                CHECK (identity_digest ~ '^sha256:[0-9a-f]{64}$'),
            record_digest TEXT NOT NULL
                CHECK (record_digest ~ '^sha256:[0-9a-f]{64}$'),
            record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
        );

        REVOKE ALL PRIVILEGES ON TABLE target_dispatch_fence
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT, UPDATE ON TABLE target_dispatch_fence TO fdai_core;
