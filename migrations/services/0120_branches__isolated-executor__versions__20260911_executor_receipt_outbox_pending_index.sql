-- Migration Revision: executor_outbox_pending_index_20260911
-- Down Revision: executor_runtime_role_20260808
-- Owner: isolated-executor
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE INDEX IF NOT EXISTS ix_executor_receipt_outbox_pending ON executor_receipt_outbox (next_attempt_at, created_at, receipt_id);
