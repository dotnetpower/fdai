-- Migration Revision: core_executor_audit_intent_20260910
-- Down Revision: core_executor_idempotency_reservation_20260910
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE executor_audit_intent (
            intent_key TEXT PRIMARY KEY
                CHECK (intent_key ~ '^sha256:[0-9a-f]{64}$'),
            intent_digest TEXT NOT NULL
                CHECK (intent_digest ~ '^sha256:[0-9a-f]{64}$'),
            record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
        );

        REVOKE ALL PRIVILEGES ON TABLE executor_audit_intent
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT ON TABLE executor_audit_intent TO fdai_core;
