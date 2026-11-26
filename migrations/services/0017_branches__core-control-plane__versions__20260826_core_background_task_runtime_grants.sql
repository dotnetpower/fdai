-- Migration Revision: core_background_task_runtime_grants_20260826
-- Down Revision: core_canonical_incident_projection_20260825
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE
            background_task_attempt,
            background_task_progress,
            background_task_completion
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT, UPDATE, DELETE
            ON TABLE background_task_attempt TO fdai_core;
        GRANT SELECT, INSERT
            ON TABLE background_task_progress TO fdai_core;
        GRANT SELECT, INSERT, UPDATE
            ON TABLE background_task_completion TO fdai_core;
