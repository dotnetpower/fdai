-- Migration Revision: core_hil_park_queue_index_20260921
-- Down Revision: core_inventory_progress_retention_20260921
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE INDEX CONCURRENTLY IF NOT EXISTS state_kv_hil_park_queue_idx ON state_kv ((value ->> 'status'), updated_at DESC, key DESC) WHERE key LIKE 'hil_park:%';
