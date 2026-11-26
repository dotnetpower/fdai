"""schedule_kinds: one-shot, timezone cron, and event-exit definitions

Revision ID: 20260717_0029
Revises: 20260717_0028
Create Date: 2026-07-17 12:00:00+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260717_0029"
down_revision: str | None = "20260717_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE scheduled_task
            ADD COLUMN schedule_kind TEXT,
            ADD COLUMN timezone TEXT NOT NULL DEFAULT 'UTC',
            ADD COLUMN exit_event_type TEXT,
            ADD COLUMN exit_observed_at TIMESTAMPTZ;

        UPDATE scheduled_task
           SET schedule_kind = CASE
               WHEN cron_expression IS NOT NULL THEN 'cron'
               ELSE 'interval'
           END;

        ALTER TABLE scheduled_task
            ALTER COLUMN schedule_kind SET NOT NULL,
            ADD CONSTRAINT scheduled_task_kind_check CHECK (
                schedule_kind IN ('interval', 'one-shot', 'cron', 'event-exit')
            ),
            ADD CONSTRAINT scheduled_task_kind_fields_check CHECK (
                (schedule_kind = 'cron' AND cron_expression IS NOT NULL)
                OR (schedule_kind <> 'cron' AND cron_expression IS NULL)
            ),
            ADD CONSTRAINT scheduled_task_exit_fields_check CHECK (
                (schedule_kind = 'event-exit' AND exit_event_type IS NOT NULL)
                OR (
                    schedule_kind <> 'event-exit'
                    AND exit_event_type IS NULL
                    AND exit_observed_at IS NULL
                )
            );

        CREATE INDEX idx_scheduled_task_exit_event
            ON scheduled_task(exit_event_type)
            WHERE schedule_kind = 'event-exit' AND enabled = TRUE;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_scheduled_task_exit_event;")
    op.execute("ALTER TABLE scheduled_task DROP CONSTRAINT scheduled_task_exit_fields_check;")
    op.execute("ALTER TABLE scheduled_task DROP CONSTRAINT scheduled_task_kind_fields_check;")
    op.execute("ALTER TABLE scheduled_task DROP CONSTRAINT scheduled_task_kind_check;")
    op.execute("ALTER TABLE scheduled_task DROP COLUMN exit_observed_at;")
    op.execute("ALTER TABLE scheduled_task DROP COLUMN exit_event_type;")
    op.execute("ALTER TABLE scheduled_task DROP COLUMN timezone;")
    op.execute("ALTER TABLE scheduled_task DROP COLUMN schedule_kind;")
