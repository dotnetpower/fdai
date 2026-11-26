-- Migration Revision: operator_completion_retention_20260829
-- Down Revision: operator_cost_governance_20260828
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE DELETE ON TABLE operator_read_investigation_completion
        FROM PUBLIC;
        GRANT DELETE ON TABLE operator_read_investigation_completion
        TO fdai_operator;
