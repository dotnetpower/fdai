-- Migration Revision: core_t2_cache_lookup_repair_20260906
-- Down Revision: core_operational_history_lifecycle_20260906
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
DROP INDEX IF EXISTS idx_t2_cache_expires_at;
        CREATE INDEX IF NOT EXISTS idx_t2_cache_lookup
            ON t2_cache (catalog_version, input_hash, expires_at DESC, created_at DESC);
