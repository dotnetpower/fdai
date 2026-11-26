-- Migration Revision: operator_background_task_read_20260823
-- Down Revision: operator_inventory_realtime_read_20260822
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE
            background_task_attempt,
            background_task_progress,
            background_task_completion
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE
            background_task_attempt,
            background_task_progress,
            background_task_completion
        TO fdai_operator;
