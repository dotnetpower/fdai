-- Migration Revision: 20260716_0022
-- Down Revision: 20260716_0021
-- Owner: alembic
-- Extracted SQL Blocks: 2

-- Statement 1
CREATE TABLE user_context_projection_upsert_queue (projection_kind TEXT NOT NULL CHECK (projection_kind IN ('conversation_bundle', 'preference', 'memory', 'policy', 'briefing_subscription', 'briefing_run', 'workflow_definition', 'workflow_binding')), principal_id TEXT NOT NULL, record_id TEXT NOT NULL, available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0), leased_until TIMESTAMPTZ, last_error TEXT, PRIMARY KEY (projection_kind, principal_id, record_id));

-- Statement 2
CREATE INDEX ix_user_context_projection_upsert_available ON user_context_projection_upsert_queue (available_at);
