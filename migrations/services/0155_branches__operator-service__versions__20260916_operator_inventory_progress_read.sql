-- Migration Revision: operator_inventory_progress_read_20260916
-- Down Revision: operator_browser_evidence_workspace_20260915
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE inventory_progress_event
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE inventory_progress_event TO fdai_operator;
