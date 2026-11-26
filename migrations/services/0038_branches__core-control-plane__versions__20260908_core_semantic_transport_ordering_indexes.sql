-- Migration Revision: core_semantic_transport_ordering_20260908
-- Down Revision: core_semantic_transport_indexes_20260908
-- Owner: core-control-plane
-- Extracted SQL Blocks: 2

-- Statement 1
DROP INDEX CONCURRENTLY IF EXISTS state_kv_operator_semantic_claim_order_idx;

-- Statement 2
CREATE INDEX CONCURRENTLY state_kv_operator_semantic_claim_order_idx ON state_kv ((COALESCE(value ->> 'outbox_namespace', '')), (value ->> 'accepted_at'), key) WHERE value ->> 'kind' = 'operator.semantic_turn' AND (value ->> 'state' = 'pending' OR value ->> 'state' = 'claimed');
