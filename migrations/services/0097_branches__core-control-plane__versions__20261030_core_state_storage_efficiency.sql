-- Migration Revision: core_state_storage_efficiency_20261030
-- Down Revision: core_inventory_storage_efficiency_20261030
-- Owner: core-control-plane
-- Extracted SQL Blocks: 7

-- Statement 1
SET LOCAL statement_timeout = '15s'; SET LOCAL lock_timeout = '2s'; ALTER TABLE state_kv SET (autovacuum_vacuum_scale_factor=0.01, autovacuum_vacuum_threshold=1000, toast.autovacuum_vacuum_scale_factor=0.01, toast.autovacuum_vacuum_threshold=1000);

-- Statement 2
SET statement_timeout = '15s';

-- Statement 3
SET lock_timeout = '2s';

-- Statement 4
DROP INDEX CONCURRENTLY IF EXISTS state_kv_conversation_summary_idx;

-- Statement 5
CREATE INDEX CONCURRENTLY state_kv_conversation_summary_idx ON state_kv ((value ->> 'principal_id'), (value #>> '{envelope,semantic_turn,session_id}'), (value ->> 'accepted_at'), key) WHERE value ->> 'kind' = 'operator.semantic_turn';

-- Statement 6
RESET lock_timeout;

-- Statement 7
RESET statement_timeout;
