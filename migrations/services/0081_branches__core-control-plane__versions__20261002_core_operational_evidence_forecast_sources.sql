-- Migration Revision: core_operational_evidence_forecast_sources_20261002
-- Down Revision: core_licensing_entitlement_state_20261001
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
GRANT SELECT ON TABLE
            operational_state_transition_batch,
            operational_state_transition,
            operational_state_transition_coverage
        TO fdai_operational_evidence_verifier;
