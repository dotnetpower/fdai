-- Migration Revision: core_licensing_entitlement_state_20261001
-- Down Revision: core_operator_receipt_source_20260930
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE licensing_entitlement_state (
            singleton BOOLEAN PRIMARY KEY DEFAULT TRUE,
            notice TEXT NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT licensing_entitlement_state_is_singleton CHECK (singleton),
            CONSTRAINT licensing_entitlement_state_notice
                CHECK (notice IN ('none', 'evaluation-ended', 'not-activated'))
        );

        REVOKE ALL ON TABLE licensing_entitlement_state FROM PUBLIC;
        GRANT SELECT, INSERT, UPDATE ON TABLE licensing_entitlement_state TO fdai_core;
