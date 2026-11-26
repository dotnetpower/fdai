-- Migration Revision: core_inventory_routes_links_20260810
-- Down Revision: core_topology_history_20260810
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
ALTER TABLE inventory_snapshot_link
            DROP CONSTRAINT inventory_snapshot_link_link_type_check;
        ALTER TABLE inventory_snapshot_link
            ADD CONSTRAINT inventory_snapshot_link_link_type_check
            CHECK (link_type IN
                ('contains', 'attached_to', 'depends_on', 'peered_with', 'routes_to'));
        ALTER TABLE inventory_realtime_link
            DROP CONSTRAINT inventory_realtime_link_link_type_check;
        ALTER TABLE inventory_realtime_link
            ADD CONSTRAINT inventory_realtime_link_link_type_check
            CHECK (link_type IN
                ('contains', 'attached_to', 'depends_on', 'peered_with', 'routes_to'));
