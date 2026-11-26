-- Migration Revision: core_safeguard_dispatch_evidence_20260911
-- Down Revision: core_target_dispatch_fence_20260910
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE safeguard_dispatch_evidence (
            target_digest TEXT NOT NULL
                CHECK (target_digest ~ '^sha256:[0-9a-f]{64}$'),
            generation INTEGER NOT NULL CHECK (generation > 0),
            revision INTEGER NOT NULL CHECK (revision > 0),
            state TEXT NOT NULL CHECK (
                state IN (
                    'bundle_persisted',
                    'dispatch_started',
                    'dispatch_observed',
                    'pre_release'
                )
            ),
            evidence_identity_digest TEXT NOT NULL
                CHECK (evidence_identity_digest ~ '^sha256:[0-9a-f]{64}$'),
            record_digest TEXT NOT NULL
                CHECK (record_digest ~ '^sha256:[0-9a-f]{64}$'),
            record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (target_digest, generation)
        );

        REVOKE ALL PRIVILEGES ON TABLE safeguard_dispatch_evidence
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT, UPDATE ON TABLE safeguard_dispatch_evidence TO fdai_core;
