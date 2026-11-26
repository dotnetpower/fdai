-- Migration Revision: operator_index_maintenance_20260825
-- Down Revision: operator_background_task_read_20260823
-- Owner: operator-service
-- Extracted SQL Blocks: 2

-- Statement 1
DROP INDEX CONCURRENTLY IF EXISTS conversation_outbound_delivery_attempt_delivery_idx;

-- Statement 2
DROP INDEX CONCURRENTLY IF EXISTS ix_conversation_turn_history;
