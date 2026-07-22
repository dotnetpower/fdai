"""durable background task completion outbox

Revision ID: 20260722_0051
Revises: 20260721_0050
Create Date: 2026-07-22 09:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260722_0051"
down_revision: str | None = "20260721_0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE background_task_completion (
            attempt_id TEXT PRIMARY KEY REFERENCES background_task_attempt(attempt_id)
                ON DELETE CASCADE,
            state TEXT NOT NULL CHECK (state IN (
                'pending', 'sending', 'failed', 'delivered', 'abandoned'
            )),
            created_at TIMESTAMPTZ NOT NULL,
            due_at TIMESTAMPTZ NOT NULL,
            retention_until TIMESTAMPTZ NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (
                attempt_count BETWEEN 0 AND 8
            ),
            lease_owner TEXT CHECK (
                lease_owner IS NULL OR char_length(lease_owner) BETWEEN 1 AND 256
            ),
            lease_token TEXT CHECK (
                lease_token IS NULL OR char_length(lease_token) BETWEEN 1 AND 256
            ),
            lease_expires_at TIMESTAMPTZ,
            last_error_code TEXT CHECK (
                last_error_code IS NULL
                OR char_length(last_error_code) BETWEEN 1 AND 256
            ),
            terminal_at TIMESTAMPTZ,
            CHECK (created_at <= due_at AND due_at <= retention_until),
            CHECK (
                (state = 'pending'
                    AND attempt_count = 0
                    AND lease_owner IS NULL
                    AND lease_token IS NULL
                    AND lease_expires_at IS NULL
                    AND last_error_code IS NULL
                    AND terminal_at IS NULL)
                OR (state = 'sending'
                    AND attempt_count BETWEEN 1 AND 8
                    AND lease_owner IS NOT NULL
                    AND lease_token IS NOT NULL
                    AND lease_expires_at IS NOT NULL
                    AND last_error_code IS NULL
                    AND terminal_at IS NULL)
                OR (state = 'failed'
                    AND attempt_count BETWEEN 1 AND 8
                    AND lease_owner IS NULL
                    AND lease_token IS NULL
                    AND lease_expires_at IS NULL
                    AND last_error_code IS NOT NULL
                    AND terminal_at IS NULL)
                OR (state = 'delivered'
                    AND attempt_count BETWEEN 1 AND 8
                    AND lease_owner IS NULL
                    AND lease_token IS NULL
                    AND lease_expires_at IS NULL
                    AND last_error_code IS NULL
                    AND terminal_at IS NOT NULL)
                OR (state = 'abandoned'
                    AND attempt_count BETWEEN 1 AND 8
                    AND lease_owner IS NULL
                    AND lease_token IS NULL
                    AND lease_expires_at IS NULL
                    AND last_error_code IS NOT NULL
                    AND terminal_at IS NOT NULL)
            )
        );
        CREATE INDEX ix_background_task_completion_due
            ON background_task_completion (due_at, attempt_id)
            WHERE state IN ('pending', 'failed');
        CREATE INDEX ix_background_task_completion_retention
            ON background_task_completion (retention_until, attempt_id)
            WHERE state IN ('delivered', 'abandoned');

        INSERT INTO background_task_completion (
            attempt_id, state, created_at, due_at, retention_until,
            attempt_count, lease_owner, lease_token, lease_expires_at,
            last_error_code, terminal_at
        )
        SELECT
            attempt_id, 'pending', updated_at, updated_at,
            GREATEST(retention_until, updated_at),
            0, NULL, NULL, NULL, NULL, NULL
        FROM background_task_attempt
        WHERE status IN ('succeeded', 'failed', 'cancelled', 'timed_out', 'unknown');
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS background_task_completion;")
