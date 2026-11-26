-- Migration Revision: core_runtime_call_snapshot_links_20260912
-- Down Revision: core_post_release_closure_20260912
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
ALTER TABLE inventory_snapshot_link
            DROP CONSTRAINT inventory_snapshot_link_link_type_check;
        ALTER TABLE inventory_snapshot_link
            ADD CONSTRAINT inventory_snapshot_link_link_type_check
            CHECK (link_type IN (
                'contains', 'attached_to', 'depends_on', 'peered_with', 'routes_to',
                'kubernetes_scheduled_on', 'kubernetes_backed_by',
                'kubernetes_owned_by', 'kubernetes_selects',
                'kubernetes_exposes_endpoints', 'kubernetes_exposes_endpoint_slice',
                'runtime_calls'
            ));
        ALTER TABLE inventory_realtime_link
            DROP CONSTRAINT inventory_realtime_link_link_type_check;
        ALTER TABLE inventory_realtime_link
            ADD CONSTRAINT inventory_realtime_link_link_type_check
            CHECK (link_type IN (
                'contains', 'attached_to', 'depends_on', 'peered_with', 'routes_to',
                'kubernetes_scheduled_on', 'kubernetes_backed_by',
                'kubernetes_owned_by', 'kubernetes_selects',
                'kubernetes_exposes_endpoints', 'kubernetes_exposes_endpoint_slice',
                'runtime_calls'
            ));
