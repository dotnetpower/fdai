-- Migration Revision: core_query_index_maintenance_20260825
-- Down Revision: core_metering_sequence_20260825
-- Owner: core-control-plane
-- Extracted SQL Blocks: 2

-- Statement 1
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_state_kv_key_prefix ON state_kv (key text_pattern_ops);

-- Statement 2
DROP INDEX CONCURRENTLY IF EXISTS idx_question_campaign_attempt_case;
