-- Migration Revision: 20260716_0020
-- Down Revision: 20260716_0019
-- Owner: alembic
-- Extracted SQL Blocks: 12

-- Statement 1
ALTER TABLE conversation_record ADD COLUMN next_turn_index BIGINT NOT NULL DEFAULT 0 CHECK (next_turn_index >= 0);

-- Statement 2
UPDATE conversation_record AS conversation SET next_turn_index = COALESCE((SELECT MAX(turn_index) + 1 FROM conversation_turn AS turn WHERE turn.principal_id = conversation.principal_id AND turn.conversation_id = conversation.conversation_id), 0);

-- Statement 3
CREATE INDEX ix_user_memory_expiry ON user_memory_fact (expires_at) WHERE expires_at IS NOT NULL;

-- Statement 4
CREATE INDEX ix_conversation_policy_source_turn ON conversation_policy (principal_id, source_turn_id);

-- Statement 5
ALTER TABLE briefing_subscription ADD CONSTRAINT ck_briefing_subscription_lateness_cap CHECK (max_lateness_seconds <= 604800);

-- Statement 6
ALTER TABLE briefing_run ADD CONSTRAINT ck_briefing_run_title_size CHECK (char_length(title) <= 200);

-- Statement 7
ALTER TABLE briefing_run ADD CONSTRAINT ck_briefing_run_body_size CHECK (char_length(body_markdown) <= 100000);

-- Statement 8
CREATE UNIQUE INDEX uq_workflow_binding_equivalent ON workflow_binding (principal_id, definition_id, trigger, COALESCE(scope_ref, ''), COALESCE(cron_expression, ''), COALESCE(timezone, ''), COALESCE(signal_type, ''));

-- Statement 9
ALTER TABLE user_memory_fact DROP CONSTRAINT user_memory_fact_principal_id_superseded_by_fkey;

-- Statement 10
ALTER TABLE user_memory_fact ADD CONSTRAINT user_memory_fact_principal_id_superseded_by_fkey FOREIGN KEY (principal_id, superseded_by) REFERENCES user_memory_fact(principal_id, memory_id) ON DELETE SET NULL;

-- Statement 11
CREATE TABLE user_context_projection_delete_queue (object_id TEXT PRIMARY KEY, available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0), leased_until TIMESTAMPTZ, last_error TEXT);

-- Statement 12
CREATE INDEX ix_user_context_projection_delete_available ON user_context_projection_delete_queue (available_at);
