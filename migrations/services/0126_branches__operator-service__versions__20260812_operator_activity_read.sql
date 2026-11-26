-- Migration Revision: operator_activity_read_20260812
-- Down Revision: operator_metering_read_20260810
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE
            inventory_snapshot,
            inventory_snapshot_resource,
            inventory_snapshot_link
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE
            inventory_snapshot,
            inventory_snapshot_resource,
            inventory_snapshot_link
        TO fdai_operator;
