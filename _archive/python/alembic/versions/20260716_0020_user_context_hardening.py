"""user context hardening: atomic turn allocation and retention indexes

Revision ID: 20260716_0020
Revises: 20260716_0019
Create Date: 2026-07-16 16:45:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260716_0020"
down_revision: str | None = "20260716_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE conversation_record "
        "ADD COLUMN next_turn_index BIGINT NOT NULL DEFAULT 0 "
        "CHECK (next_turn_index >= 0);"
    )
    op.execute(
        "UPDATE conversation_record AS conversation "
        "SET next_turn_index = COALESCE(("
        "SELECT MAX(turn_index) + 1 FROM conversation_turn AS turn "
        "WHERE turn.principal_id = conversation.principal_id "
        "AND turn.conversation_id = conversation.conversation_id"
        "), 0);"
    )
    op.execute(
        "CREATE INDEX ix_user_memory_expiry "
        "ON user_memory_fact (expires_at) WHERE expires_at IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_conversation_policy_source_turn "
        "ON conversation_policy (principal_id, source_turn_id);"
    )
    op.execute(
        "ALTER TABLE briefing_subscription ADD CONSTRAINT "
        "ck_briefing_subscription_lateness_cap "
        "CHECK (max_lateness_seconds <= 604800);"
    )
    op.execute(
        "ALTER TABLE briefing_run ADD CONSTRAINT ck_briefing_run_title_size "
        "CHECK (char_length(title) <= 200);"
    )
    op.execute(
        "ALTER TABLE briefing_run ADD CONSTRAINT ck_briefing_run_body_size "
        "CHECK (char_length(body_markdown) <= 100000);"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_workflow_binding_equivalent "
        "ON workflow_binding (principal_id, definition_id, trigger, "
        "COALESCE(scope_ref, ''), COALESCE(cron_expression, ''), "
        "COALESCE(timezone, ''), COALESCE(signal_type, ''));"
    )
    op.execute(
        "ALTER TABLE user_memory_fact DROP CONSTRAINT "
        "user_memory_fact_principal_id_superseded_by_fkey;"
    )
    op.execute(
        "ALTER TABLE user_memory_fact ADD CONSTRAINT "
        "user_memory_fact_principal_id_superseded_by_fkey "
        "FOREIGN KEY (principal_id, superseded_by) "
        "REFERENCES user_memory_fact(principal_id, memory_id) ON DELETE SET NULL;"
    )
    op.execute(
        "CREATE TABLE user_context_projection_delete_queue ("
        "object_id TEXT PRIMARY KEY, "
        "available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
        "attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0), "
        "leased_until TIMESTAMPTZ, "
        "last_error TEXT"
        ");"
    )
    op.execute(
        "CREATE INDEX ix_user_context_projection_delete_available "
        "ON user_context_projection_delete_queue (available_at);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_context_projection_delete_queue;")
    op.execute(
        "ALTER TABLE user_memory_fact DROP CONSTRAINT "
        "user_memory_fact_principal_id_superseded_by_fkey;"
    )
    op.execute(
        "ALTER TABLE user_memory_fact ADD CONSTRAINT "
        "user_memory_fact_principal_id_superseded_by_fkey "
        "FOREIGN KEY (principal_id, superseded_by) "
        "REFERENCES user_memory_fact(principal_id, memory_id);"
    )
    op.execute("DROP INDEX IF EXISTS uq_workflow_binding_equivalent;")
    op.execute("ALTER TABLE briefing_run DROP CONSTRAINT ck_briefing_run_body_size;")
    op.execute("ALTER TABLE briefing_run DROP CONSTRAINT ck_briefing_run_title_size;")
    op.execute(
        "ALTER TABLE briefing_subscription DROP CONSTRAINT ck_briefing_subscription_lateness_cap;"
    )
    op.execute("DROP INDEX IF EXISTS ix_conversation_policy_source_turn;")
    op.execute("DROP INDEX IF EXISTS ix_user_memory_expiry;")
    op.execute("ALTER TABLE conversation_record DROP COLUMN next_turn_index;")
