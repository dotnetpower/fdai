-- Migration Revision: operator_cost_governance_live_read_20260917
-- Down Revision: operator_forecast_retention_20260917
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE
            cost_observation_current,
            cost_governance_analytics_run_receipt,
            cost_governance_case_projection,
            cost_governance_episode,
            cost_governance_evidence,
            cost_governance_recovery,
            cost_governance_retention,
            cost_governance_settlement,
            cost_governance_effect_settlement
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE
            cost_observation_current,
            cost_governance_analytics_run_receipt,
            cost_governance_case_projection,
            cost_governance_episode,
            cost_governance_evidence,
            cost_governance_recovery,
            cost_governance_retention,
            cost_governance_settlement,
            cost_governance_effect_settlement
        TO fdai_operator;
