-- Migration Revision: 20260717_0029
-- Down Revision: 20260717_0028
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
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
