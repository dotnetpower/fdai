-- Migration Revision: operator_projection_update_grants_20260830
-- Down Revision: operator_background_task_projection_transport_20260829
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
GRANT UPDATE (completion_id)
        ON TABLE operator_read_investigation_completion TO fdai_operator;
        GRANT UPDATE (task_id)
        ON TABLE operator_background_task_progress TO fdai_operator;
