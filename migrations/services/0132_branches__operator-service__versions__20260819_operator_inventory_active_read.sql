-- Migration Revision: operator_inventory_active_read_20260819
-- Down Revision: operator_incident_projection_read_20260819
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE inventory_active
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE inventory_active TO fdai_operator;
