"""background task projection transport ordering and outbox fields

Revision ID: 20260829_0088
Revises: 20260826_0087
Create Date: 2026-08-29 04:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260829_0088"
down_revision: str | None = "20260826_0087"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE SEQUENCE background_task_progress_append_order_seq AS BIGINT;
        ALTER TABLE background_task_progress
            ADD COLUMN append_order BIGINT;
        ALTER TABLE background_task_progress
            ALTER COLUMN append_order SET DEFAULT nextval(
                'background_task_progress_append_order_seq'
            );
        ALTER SEQUENCE background_task_progress_append_order_seq
            OWNED BY background_task_progress.append_order;
        WITH ordered AS (
            SELECT ctid,
                   row_number() OVER (ORDER BY at, attempt_id, sequence) AS append_order
              FROM background_task_progress
             WHERE append_order IS NULL
        )
        UPDATE background_task_progress AS progress
           SET append_order = ordered.append_order
          FROM ordered
         WHERE progress.ctid = ordered.ctid;
        SELECT setval(
            'background_task_progress_append_order_seq',
            COALESCE((SELECT MAX(append_order) FROM background_task_progress), 1),
            EXISTS (SELECT 1 FROM background_task_progress)
        );
        ALTER TABLE background_task_progress
            ALTER COLUMN append_order SET NOT NULL;
        CREATE UNIQUE INDEX ix_background_task_progress_append_order
            ON background_task_progress (append_order);

        ALTER TABLE background_task_completion
            ADD COLUMN updated_at TIMESTAMPTZ;
        UPDATE background_task_completion
           SET updated_at = COALESCE(terminal_at, created_at)
         WHERE updated_at IS NULL;
        ALTER TABLE background_task_completion
            ALTER COLUMN updated_at SET NOT NULL;
        ALTER TABLE background_task_completion
            ADD COLUMN progress_watermark BIGINT;
        UPDATE background_task_completion AS completion
           SET progress_watermark = progress.max_append_order
          FROM (
              SELECT attempt_id, MAX(append_order) AS max_append_order
                FROM background_task_progress
               GROUP BY attempt_id
          ) AS progress
         WHERE completion.attempt_id = progress.attempt_id
           AND completion.progress_watermark IS NULL;
        UPDATE background_task_completion
           SET progress_watermark = 0
         WHERE progress_watermark IS NULL;
        ALTER TABLE background_task_completion
            ALTER COLUMN progress_watermark SET NOT NULL;
        ALTER TABLE background_task_completion
            ADD CONSTRAINT background_task_completion_progress_watermark_check
                CHECK (progress_watermark >= 0);

        CREATE TABLE background_task_projection_outbox (
            outbox_sequence BIGSERIAL PRIMARY KEY,
            projection_id TEXT NOT NULL UNIQUE CHECK (
                projection_id ~ '^background-task-(snapshot|progress)-[a-f0-9]{32}$'
            ),
            task_id TEXT NOT NULL CHECK (char_length(task_id) BETWEEN 1 AND 256),
            attempt_id TEXT NOT NULL REFERENCES background_task_attempt(attempt_id)
                ON DELETE CASCADE,
            record_kind TEXT NOT NULL CHECK (record_kind IN ('snapshot', 'progress')),
            projection_sequence BIGINT NULL CHECK (
                projection_sequence IS NULL OR projection_sequence >= 1
            ),
            progress_sequence INTEGER NULL CHECK (
                progress_sequence IS NULL OR progress_sequence BETWEEN 0 AND 255
            ),
            progress_order BIGINT NULL CHECK (
                progress_order IS NULL OR progress_order >= 1
            ),
            progress_watermark BIGINT NULL CHECK (
                progress_watermark IS NULL OR progress_watermark >= 0
            ),
            retention_until TIMESTAMPTZ NOT NULL,
            payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
            claim_count INTEGER NOT NULL DEFAULT 0 CHECK (claim_count >= 0),
            claimed_at TIMESTAMPTZ NULL,
            lease_owner TEXT NULL CHECK (
                lease_owner IS NULL OR char_length(lease_owner) BETWEEN 1 AND 256
            ),
            lease_token TEXT NULL CHECK (
                lease_token IS NULL OR char_length(lease_token) BETWEEN 1 AND 256
            ),
            lease_expires_at TIMESTAMPTZ NULL,
            last_error_code TEXT NULL CHECK (
                last_error_code IS NULL OR char_length(last_error_code) BETWEEN 1 AND 256
            ),
            published_at TIMESTAMPTZ NULL,
            CHECK (
                (record_kind = 'snapshot'
                    AND projection_sequence IS NOT NULL
                    AND progress_sequence IS NULL
                    AND progress_order IS NULL)
                OR (record_kind = 'progress'
                    AND projection_sequence IS NULL
                    AND progress_sequence IS NOT NULL
                    AND progress_order IS NOT NULL
                    AND progress_watermark IS NULL)
            ),
            CHECK (
                (lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL)
                OR (lease_owner IS NOT NULL
                    AND lease_token IS NOT NULL
                    AND lease_expires_at IS NOT NULL)
            ),
            CHECK (
                published_at IS NULL
                OR (lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL)
            )
        );
        CREATE INDEX ix_background_task_projection_outbox_pending
            ON background_task_projection_outbox (outbox_sequence)
            WHERE published_at IS NULL;
        CREATE INDEX ix_background_task_projection_outbox_attempt_progress
            ON background_task_projection_outbox (attempt_id, progress_order)
            WHERE record_kind = 'progress' AND published_at IS NULL;
        CREATE INDEX ix_background_task_projection_outbox_retention
            ON background_task_projection_outbox (retention_until, outbox_sequence)
            WHERE published_at IS NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE background_task_completion
            DROP CONSTRAINT IF EXISTS background_task_completion_progress_watermark_check;
        DROP INDEX IF EXISTS ix_background_task_projection_outbox_retention;
        DROP INDEX IF EXISTS ix_background_task_projection_outbox_attempt_progress;
        DROP INDEX IF EXISTS ix_background_task_projection_outbox_pending;
        DROP TABLE IF EXISTS background_task_projection_outbox;
        ALTER TABLE background_task_completion
            DROP COLUMN IF EXISTS progress_watermark;
        ALTER TABLE background_task_completion
            DROP COLUMN IF EXISTS updated_at;
        DROP INDEX IF EXISTS ix_background_task_progress_append_order;
        ALTER TABLE background_task_progress
            ALTER COLUMN append_order DROP DEFAULT;
        ALTER TABLE background_task_progress
            DROP COLUMN IF EXISTS append_order;
        DROP SEQUENCE IF EXISTS background_task_progress_append_order_seq;
        """
    )
