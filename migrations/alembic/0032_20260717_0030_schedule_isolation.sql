-- Migration Revision: 20260717_0030
-- Down Revision: 20260717_0029
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
ALTER TABLE scheduled_task ADD COLUMN isolation_profile JSONB NOT NULL DEFAULT
        '{
          "profile_id": "scheduled.default-deny",
          "max_session_seconds": 300,
          "max_context_chars": 16000,
          "max_tool_calls": 0,
          "allowed_tool_ids": [],
          "command_sandbox_profile_id": null
        }'::jsonb;
        ALTER TABLE scheduled_task ADD CONSTRAINT scheduled_task_isolation_object CHECK (
            jsonb_typeof(isolation_profile) = 'object'
        );
