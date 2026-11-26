-- Migration Revision: core_semantic_transport_indexes_20260908
-- Down Revision: core_oi16_synthetic_retention_20260907
-- Owner: core-control-plane
-- Extracted SQL Blocks: 4

-- Statement 1
DROP INDEX CONCURRENTLY IF EXISTS state_kv_operator_semantic_claim_idx;

-- Statement 2
CREATE INDEX CONCURRENTLY state_kv_operator_semantic_claim_idx ON state_kv ((COALESCE(value ->> 'outbox_namespace', '')), (value ->> 'state'), (value ->> 'accepted_at'), key) WHERE value ->> 'kind' = 'operator.semantic_turn';

-- Statement 3
DROP INDEX CONCURRENTLY IF EXISTS state_kv_operator_semantic_replay_idx;

-- Statement 4
CREATE INDEX CONCURRENTLY state_kv_operator_semantic_replay_idx ON state_kv ((value ->> 'principal_id'), (value ->> 'request_id'), ((value ->> 'event_sequence')::bigint)) WHERE key LIKE 'operator-semantic-result:%';
