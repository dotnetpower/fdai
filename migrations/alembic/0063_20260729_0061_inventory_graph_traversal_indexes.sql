-- Migration Revision: 20260729_0061
-- Down Revision: 20260729_0060
-- Owner: alembic
-- Extracted SQL Blocks: 2

-- Statement 1
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_inventory_snapshot_link_reverse ON inventory_snapshot_link(snapshot_id, to_id, link_type, from_id);

-- Statement 2
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_inventory_realtime_link_reverse ON inventory_realtime_link(to_id, link_type, from_id);
