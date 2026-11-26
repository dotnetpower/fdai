-- Migration Revision: core_inventory_coverage_indexes_20260919
-- Down Revision: core_knowledge_read_20260917
-- Owner: core-control-plane
-- Extracted SQL Blocks: 2

-- Statement 1
CREATE INDEX CONCURRENTLY IF NOT EXISTS inventory_observation_journal_scope_watermark_idx ON inventory_observation_journal (scope_ref, watermark) INCLUDE (source_revision, effective_at);

-- Statement 2
CREATE INDEX CONCURRENTLY IF NOT EXISTS inventory_correction_pending_scope_watermark_idx ON inventory_observation_partition (scope_ref, last_watermark) WHERE state='correction_pending';
