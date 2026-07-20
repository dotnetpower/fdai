"""durable detached background task attempts

Revision ID: 20260720_0040
Revises: 20260720_0039
Create Date: 2026-07-20 10:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260720_0040"
down_revision: str | None = "20260720_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE background_task_attempt (
            attempt_id TEXT PRIMARY KEY CHECK (
                char_length(attempt_id) BETWEEN 1 AND 256
            ),
            task_id TEXT NOT NULL UNIQUE CHECK (
                char_length(task_id) BETWEEN 1 AND 256
            ),
            owner_principal_id TEXT NOT NULL CHECK (
                char_length(owner_principal_id) BETWEEN 1 AND 256
            ),
            idempotency_key TEXT NOT NULL CHECK (
                char_length(idempotency_key) BETWEEN 1 AND 256
            ),
            task JSONB NOT NULL CHECK (jsonb_typeof(task) = 'object'),
            attempt_number INTEGER NOT NULL DEFAULT 1 CHECK (attempt_number = 1),
            status TEXT NOT NULL CHECK (status IN (
                'queued', 'claimed', 'running', 'succeeded', 'failed',
                'cancelled', 'timed_out', 'unknown'
            )),
            revision BIGINT NOT NULL DEFAULT 1 CHECK (revision >= 1),
            created_at TIMESTAMPTZ NOT NULL,
            retention_until TIMESTAMPTZ NOT NULL CHECK (retention_until > created_at),
            updated_at TIMESTAMPTZ NOT NULL,
            max_progress_events INTEGER NOT NULL CHECK (
                max_progress_events BETWEEN 1 AND 256
            ),
            lease_owner TEXT CHECK (
                lease_owner IS NULL OR char_length(lease_owner) BETWEEN 1 AND 256
            ),
            lease_token TEXT CHECK (
                lease_token IS NULL OR char_length(lease_token) BETWEEN 1 AND 256
            ),
            lease_expires_at TIMESTAMPTZ,
            usage JSONB NOT NULL CHECK (jsonb_typeof(usage) = 'object'),
            result JSONB CHECK (result IS NULL OR jsonb_typeof(result) = 'object'),
            parent_attempt_id TEXT CHECK (
                parent_attempt_id IS NULL
                OR char_length(parent_attempt_id) BETWEEN 1 AND 256
            ),
            CONSTRAINT uq_background_task_owner_idempotency
                UNIQUE (owner_principal_id, idempotency_key),
            CHECK (
                (status = 'queued'
                    AND lease_owner IS NULL
                    AND lease_token IS NULL
                    AND lease_expires_at IS NULL
                    AND result IS NULL)
                OR (status IN ('claimed', 'running')
                    AND lease_owner IS NOT NULL
                    AND lease_token IS NOT NULL
                    AND lease_expires_at IS NOT NULL
                    AND lease_expires_at > updated_at
                    AND result IS NULL)
                OR (status IN (
                        'succeeded', 'failed', 'cancelled', 'timed_out', 'unknown'
                    )
                    AND lease_owner IS NULL
                    AND lease_token IS NULL
                    AND lease_expires_at IS NULL
                    AND result IS NOT NULL)
            )
        );
        CREATE INDEX ix_background_task_claim
            ON background_task_attempt (created_at, attempt_id)
            WHERE status = 'queued';
        CREATE INDEX ix_background_task_owner
            ON background_task_attempt (
                owner_principal_id, updated_at DESC, task_id DESC
            );

        CREATE TABLE background_task_progress (
            attempt_id TEXT NOT NULL REFERENCES background_task_attempt(attempt_id)
                ON DELETE CASCADE,
            sequence INTEGER NOT NULL CHECK (sequence >= 0),
            kind TEXT NOT NULL CHECK (char_length(kind) BETWEEN 1 AND 256),
            message TEXT NOT NULL CHECK (char_length(message) BETWEEN 1 AND 1000),
            at TIMESTAMPTZ NOT NULL,
            usage JSONB NOT NULL CHECK (jsonb_typeof(usage) = 'object'),
            PRIMARY KEY (attempt_id, sequence)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS background_task_progress;")
    op.execute("DROP INDEX IF EXISTS ix_background_task_owner;")
    op.execute("DROP INDEX IF EXISTS ix_background_task_claim;")
    op.execute("DROP TABLE IF EXISTS background_task_attempt;")
