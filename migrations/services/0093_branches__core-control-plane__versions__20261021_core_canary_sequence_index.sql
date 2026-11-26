-- Migration Revision: core_canary_sequence_index_20261021
-- Down Revision: core_document_intent_ingress_20261020
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE INDEX CONCURRENTLY IF NOT EXISTS audit_log_canary_sequence_idx ON audit_log (event_id, correlation_id, seq) WHERE actor = 'fdai.canary-job' AND action_kind IN ('control_loop.canary', 'control_loop.canary.attempt');
