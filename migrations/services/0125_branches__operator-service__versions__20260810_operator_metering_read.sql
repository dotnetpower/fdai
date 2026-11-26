-- Migration Revision: operator_metering_read_20260810
-- Down Revision: operator_runtime_role_20260808
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE llm_invocation FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE llm_invocation TO fdai_operator;
