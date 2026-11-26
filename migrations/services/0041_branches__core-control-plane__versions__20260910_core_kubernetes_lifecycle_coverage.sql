-- Migration Revision: core_kubernetes_lifecycle_coverage_20260910
-- Down Revision: core_semantic_transport_ordering_20260908
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE kubernetes_lifecycle_coverage_segment (
            coverage_segment_id TEXT PRIMARY KEY
                CHECK (coverage_segment_id ~ '^sha256:[0-9a-f]{64}$'),
            cluster_ref TEXT NOT NULL
                REFERENCES kubernetes_lifecycle_cursor(cluster_ref),
            started_at TIMESTAMPTZ NOT NULL,
            ended_at TIMESTAMPTZ NOT NULL,
            limitation TEXT NOT NULL CHECK (
                limitation IN (
                    'authorization_denied',
                    'cursor_expired',
                    'resource_event_response_invalid',
                    'result_limit',
                    'source_unavailable'
                )
            ),
            CHECK (ended_at > started_at)
        );
        CREATE INDEX kubernetes_lifecycle_coverage_segment_cluster_time_idx
            ON kubernetes_lifecycle_coverage_segment (
                cluster_ref, started_at, ended_at, coverage_segment_id
            );

        REVOKE ALL PRIVILEGES ON TABLE kubernetes_lifecycle_coverage_segment
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT
            ON TABLE kubernetes_lifecycle_coverage_segment TO fdai_core;
