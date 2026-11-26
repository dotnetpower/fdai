-- Migration Revision: operator_cost_governance_settings_read_20260831
-- Down Revision: operator_projection_update_grants_20260830
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
GRANT SELECT ON TABLE cost_governance_analytics_snapshot TO fdai_operator;
        GRANT EXECUTE ON FUNCTION fdai_set_cost_governance_enabled(
            TEXT, TEXT, BOOLEAN, BIGINT, TEXT
        ) TO fdai_operator;
