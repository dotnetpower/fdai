-- Migration Revision: core_interactive_read_investigation_20260826
-- Down Revision: core_background_task_runtime_grants_20260826
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE
            read_investigation_run,
            read_investigation_run_progress,
            read_investigation_run_completion
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT, UPDATE, DELETE
            ON TABLE read_investigation_run TO fdai_core;
        GRANT SELECT, INSERT
            ON TABLE read_investigation_run_progress TO fdai_core;
        GRANT SELECT, INSERT, UPDATE
            ON TABLE read_investigation_run_completion TO fdai_core;
