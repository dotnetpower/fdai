-- Migration Revision: operator_inventory_invalidation_read_20260906
-- Down Revision: operator_handover_document_read_20260905
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE inventory_observation_journal
            FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE inventory_observation_journal TO fdai_operator;
