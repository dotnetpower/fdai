-- Migration Revision: executor_human_access_read_20260915
-- Down Revision: executor_safeguard_bundle_read_20260912
-- Owner: isolated-executor
-- Extracted SQL Blocks: 1

-- Statement 1
GRANT EXECUTE ON FUNCTION fdai_executor_human_access_source(text, text) TO fdai_executor;
