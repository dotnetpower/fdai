-- Migration Revision: core_incident_recovery_index_20260825
-- Down Revision: core_metering_writer_20260825
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE INDEX CONCURRENTLY IF NOT EXISTS audit_log_incident_recovery_idx ON audit_log (action_kind, seq) WHERE action_kind IN ('incident.open', 'incident.members', 'incident.severity', 'incident.assigned', 'incident.ticket', 'incident.transition');
