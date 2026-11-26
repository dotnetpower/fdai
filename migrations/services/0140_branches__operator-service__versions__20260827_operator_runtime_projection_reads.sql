-- Migration Revision: operator_runtime_projection_reads_20260827
-- Down Revision: operator_interactive_read_investigation_20260826
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE
            process_runtime,
            process_event,
            automation_blueprint_candidate
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE
            process_runtime,
            process_event,
            automation_blueprint_candidate
        TO fdai_operator;
