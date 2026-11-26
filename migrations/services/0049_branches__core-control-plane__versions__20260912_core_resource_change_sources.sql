-- Migration Revision: core_resource_change_sources_20260912
-- Down Revision: core_retire_resource_change_receipts_20260912
-- Owner: core-control-plane
-- Extracted SQL Blocks: 2

-- Statement 1
DROP INDEX CONCURRENTLY inventory_observation_recent_object_change_idx;

-- Statement 2
CREATE INDEX CONCURRENTLY inventory_observation_recent_object_change_idx ON inventory_observation_journal (scope_ref, effective_at DESC, subject_ref, recorded_at DESC) INCLUDE (subject_type, operation, operation_status, mutation_kind, observation_kind, source_identity, observation_id, source_event_id, content_digest) WHERE subject_kind='object' AND ((source_identity='fdai.delivery.azure.arg_resource_changes' AND observation_kind IN ('full', 'tombstone')) OR (source_identity='azure_event_grid.resource_change' AND operation IS NOT NULL AND observation_kind IN ('partial', 'change_hint', 'tombstone')));
