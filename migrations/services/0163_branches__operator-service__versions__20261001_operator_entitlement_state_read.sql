-- Migration Revision: operator_entitlement_state_read_20261001
-- Down Revision: operator_authentication_receipts_20260929
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE licensing_entitlement_state
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE licensing_entitlement_state TO fdai_operator;
