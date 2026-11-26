"""schedule_isolation: durable default-deny scheduled session profiles

Revision ID: 20260717_0030
Revises: 20260717_0029
Create Date: 2026-07-17 12:30:00+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260717_0030"
down_revision: str | None = "20260717_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
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
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE scheduled_task DROP CONSTRAINT scheduled_task_isolation_object;")
    op.execute("ALTER TABLE scheduled_task DROP COLUMN isolation_profile;")
