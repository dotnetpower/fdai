-- Migration Revision: core_saga_compact_checkpoint_20261031
-- Down Revision: core_state_storage_efficiency_20261030
-- Owner: core-control-plane
-- Extracted SQL Blocks: 5

-- Statement 1
SET statement_timeout = '15s';

-- Statement 2
SET lock_timeout = '2s';

-- Statement 3
CREATE INDEX CONCURRENTLY audit_log_saga_entry_hash_idx ON audit_log ((entry->>'entry_hash')) WHERE jsonb_exists_all(entry::jsonb,ARRAY['correlation_id','entry_hash','payload_digest','prev_hash','principal','seq','topic']) OR (entry->>'actor'='Saga' AND entry->>'action_kind'='audit.record');

-- Statement 4
RESET lock_timeout;

-- Statement 5
RESET statement_timeout;
