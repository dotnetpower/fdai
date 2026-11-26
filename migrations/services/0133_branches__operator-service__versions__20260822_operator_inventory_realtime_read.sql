-- Migration Revision: operator_inventory_realtime_read_20260822
-- Down Revision: operator_a3_channel_delivery_20260819
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE
            inventory_realtime_resource,
            inventory_realtime_link
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE
            inventory_realtime_resource,
            inventory_realtime_link
        TO fdai_operator;
