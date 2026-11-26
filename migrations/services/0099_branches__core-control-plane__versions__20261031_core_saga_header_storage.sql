-- Migration Revision: core_saga_header_storage_20261031
-- Down Revision: core_saga_compact_checkpoint_20261031
-- Owner: core-control-plane
-- Extracted SQL Blocks: 6

-- Statement 1
SET LOCAL statement_timeout='15s'; SET LOCAL lock_timeout='2s'; ALTER TABLE audit_log ADD COLUMN saga_header JSONB GENERATED ALWAYS AS (CASE WHEN jsonb_exists_all(entry::jsonb,ARRAY['correlation_id','entry_hash','payload_digest','prev_hash','principal','seq','topic']) OR (entry->>'actor'='Saga' AND entry->>'action_kind'='audit.record') THEN jsonb_set(jsonb_set(jsonb_set(jsonb_set(jsonb_set(jsonb_set(jsonb_set('{}'::jsonb,'{seq}',entry::jsonb->'seq'),'{prev_hash}',entry::jsonb->'prev_hash'),'{entry_hash}',entry::jsonb->'entry_hash'),'{principal}',entry::jsonb->'principal'),'{topic}',entry::jsonb->'topic'),'{correlation_id}',entry::jsonb->'correlation_id'),'{payload_digest}',entry::jsonb->'payload_digest') END) STORED;

-- Statement 2
SET statement_timeout='15s';

-- Statement 3
SET lock_timeout='2s';

-- Statement 4
CREATE INDEX CONCURRENTLY audit_log_saga_header_hash_idx ON audit_log ((saga_header->>'entry_hash')) WHERE saga_header IS NOT NULL;

-- Statement 5
RESET lock_timeout;

-- Statement 6
RESET statement_timeout;
