-- Migration Revision: core_canary_age_index_20261019
-- Down Revision: core_code_security_claim_renewal_20261010
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE INDEX CONCURRENTLY IF NOT EXISTS audit_log_canary_success_latest_idx ON audit_log (seq DESC) WHERE action_kind = 'control_loop.canary' AND actor = 'fdai.canary-job' AND entry ->> 'outcome' = 'success';
