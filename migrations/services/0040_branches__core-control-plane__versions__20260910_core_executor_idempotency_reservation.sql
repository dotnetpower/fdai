-- Migration Revision: core_executor_idempotency_reservation_20260910
-- Down Revision: core_kubernetes_lifecycle_coverage_20260910
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE executor_idempotency_reservation (
            idempotency_key TEXT PRIMARY KEY
                CHECK (char_length(idempotency_key) BETWEEN 1 AND 533),
            result JSONB NOT NULL CHECK (jsonb_typeof(result) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
        );

        REVOKE ALL PRIVILEGES ON TABLE executor_idempotency_reservation
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT, UPDATE
            ON TABLE executor_idempotency_reservation TO fdai_core;
