-- Migration Revision: 20260721_0049
-- Down Revision: 20260720_0048
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE execution_submission (
            idempotency_key TEXT PRIMARY KEY,
            workload_id TEXT NOT NULL,
            artifact_digest TEXT NOT NULL CHECK (artifact_digest ~ '^[0-9a-f]{64}$'),
            profile_id TEXT NOT NULL,
            profile_version TEXT NOT NULL,
            backend_kind TEXT NOT NULL CHECK (
                backend_kind IN ('bubblewrap', 'vm_task', 'azure_container_apps_job')
            ),
            owner_trace JSONB NOT NULL CHECK (jsonb_typeof(owner_trace) = 'object'),
            stop_condition TEXT NOT NULL CHECK (length(stop_condition) > 0),
            audit_ref TEXT NOT NULL CHECK (length(audit_ref) > 0),
            scope_ref TEXT NOT NULL CHECK (length(scope_ref) > 0),
            region TEXT NOT NULL CHECK (length(region) > 0),
            status TEXT NOT NULL CHECK (
                status IN (
                    'planned', 'submitted', 'running', 'succeeded',
                    'failed', 'cancelled', 'ambiguous'
                )
            ),
            submission_ref TEXT,
            receipt_ref TEXT,
            detail TEXT NOT NULL,
            cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
            cleanup_state TEXT NOT NULL CHECK (
                cleanup_state IN ('pending', 'completed', 'provider_retention')
            ),
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            retention_until TIMESTAMPTZ NOT NULL,
            revision BIGINT NOT NULL DEFAULT 0 CHECK (revision >= 0),
            CHECK (created_at <= updated_at AND created_at < retention_until)
        );
        CREATE INDEX execution_submission_status_idx
            ON execution_submission (status, updated_at, idempotency_key);
        CREATE INDEX execution_submission_retention_idx
            ON execution_submission (retention_until, idempotency_key)
            WHERE cleanup_state = 'pending';

        CREATE TABLE execution_submission_attempt (
            idempotency_key TEXT NOT NULL REFERENCES execution_submission(idempotency_key),
            sequence INTEGER NOT NULL CHECK (sequence > 0),
            operation TEXT NOT NULL CHECK (
                operation IN ('submit', 'status', 'cancel', 'collect_receipt', 'cleanup')
            ),
            status TEXT NOT NULL CHECK (
                status IN (
                    'planned', 'submitted', 'running', 'succeeded',
                    'failed', 'cancelled', 'ambiguous'
                )
            ),
            detail TEXT NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (idempotency_key, sequence)
        );
