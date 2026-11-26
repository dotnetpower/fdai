-- Migration Revision: core_inventory_peered_links_20260810
-- Down Revision: core_runtime_role_20260809
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
ALTER TABLE inventory_snapshot_link
            DROP CONSTRAINT inventory_snapshot_link_link_type_check;
        ALTER TABLE inventory_snapshot_link
            ADD CONSTRAINT inventory_snapshot_link_link_type_check
            CHECK (link_type IN ('contains', 'attached_to', 'depends_on', 'peered_with'));
