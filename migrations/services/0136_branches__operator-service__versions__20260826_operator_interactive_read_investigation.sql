-- Migration Revision: operator_interactive_read_investigation_20260826
-- Down Revision: operator_read_investigation_completion_20260826
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE
            read_investigation_run,
            read_investigation_run_progress,
            read_investigation_run_completion
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE
            read_investigation_run,
            read_investigation_run_progress,
            read_investigation_run_completion
        TO fdai_operator;
