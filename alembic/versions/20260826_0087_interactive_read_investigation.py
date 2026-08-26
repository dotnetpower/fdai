"""add durable interactive read investigation delivery

Revision ID: 20260826_0087
Revises: 20260819_0086
Create Date: 2026-08-26 00:00:00+00:00
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0087"
down_revision: str | None = "20260819_0086"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("read_investigation_run", sa.Column("task_id", sa.Text(), nullable=True))
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT owner_principal_id, idempotency_key FROM read_investigation_run "
            "WHERE task_id IS NULL"
        )
    ).fetchall()
    for owner_principal_id, idempotency_key in rows:
        digest = hashlib.sha256(f"{owner_principal_id}\x00{idempotency_key}".encode()).hexdigest()
        connection.execute(
            sa.text(
                "UPDATE read_investigation_run SET task_id = :task_id "
                "WHERE owner_principal_id = :owner AND idempotency_key = :idempotency_key"
            ),
            {
                "task_id": f"background-{digest[:32]}",
                "owner": owner_principal_id,
                "idempotency_key": idempotency_key,
            },
        )
    op.execute(
        """
        ALTER TABLE read_investigation_run
            ALTER COLUMN task_id SET NOT NULL,
            ADD CONSTRAINT uq_read_investigation_run_task_id UNIQUE (task_id),
            ADD CONSTRAINT ck_read_investigation_run_task_id CHECK (
                char_length(task_id) BETWEEN 1 AND 256
            );

        DO $$
        DECLARE candidate TEXT;
        BEGIN
            FOR candidate IN
                SELECT conname
                  FROM pg_constraint
                 WHERE conrelid = 'read_investigation_run'::regclass
                   AND contype = 'c'
                   AND pg_get_constraintdef(oid) LIKE '%state%'
            LOOP
                EXECUTE format(
                    'ALTER TABLE read_investigation_run DROP CONSTRAINT %I',
                    candidate
                );
            END LOOP;
        END $$;

        ALTER TABLE read_investigation_run
            ADD CONSTRAINT ck_read_investigation_run_state CHECK (
                state IN (
                    'claimed', 'running', 'cancel_requested', 'completed',
                    'cancelled', 'failed', 'expired'
                )
            ),
            ADD CONSTRAINT ck_read_investigation_run_lifecycle CHECK (
                (state IN ('claimed', 'running', 'cancel_requested')
                    AND lease_owner IS NOT NULL
                    AND lease_token IS NOT NULL
                    AND lease_expires_at IS NOT NULL
                    AND result IS NULL
                    AND usage IS NULL
                    AND failure_reason IS NULL
                    AND terminal_at IS NULL)
                OR (state = 'completed'
                    AND lease_owner IS NULL
                    AND lease_token IS NULL
                    AND lease_expires_at IS NULL
                    AND result IS NOT NULL
                    AND usage IS NOT NULL
                    AND failure_reason IS NULL
                    AND terminal_at = updated_at)
                OR (state IN ('cancelled', 'failed', 'expired')
                    AND lease_owner IS NULL
                    AND lease_token IS NULL
                    AND lease_expires_at IS NULL
                    AND result IS NULL
                    AND usage IS NOT NULL
                    AND failure_reason IS NOT NULL
                    AND terminal_at = updated_at)
            );

        DROP INDEX IF EXISTS ix_read_investigation_run_claim_lease;
        CREATE INDEX ix_read_investigation_run_claim_lease
            ON read_investigation_run (lease_expires_at, owner_principal_id, idempotency_key)
            WHERE state IN ('claimed', 'running', 'cancel_requested');

        DROP INDEX IF EXISTS ix_read_investigation_run_retention;
        CREATE INDEX ix_read_investigation_run_retention
            ON read_investigation_run (retention_until, owner_principal_id, idempotency_key)
            WHERE state IN ('completed', 'cancelled', 'failed', 'expired');

        CREATE TABLE read_investigation_run_progress (
            task_id TEXT NOT NULL REFERENCES read_investigation_run(task_id) ON DELETE CASCADE,
            owner_principal_id TEXT NOT NULL CHECK (
                char_length(owner_principal_id) BETWEEN 1 AND 256
            ),
            sequence INTEGER NOT NULL CHECK (sequence BETWEEN 1 AND 256),
            kind TEXT NOT NULL CHECK (char_length(kind) BETWEEN 1 AND 128),
            recorded_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (task_id, sequence)
        );
        CREATE INDEX ix_read_investigation_run_progress_owner
            ON read_investigation_run_progress (
                owner_principal_id, task_id, sequence
            );

        CREATE TABLE read_investigation_run_completion (
            completion_id TEXT PRIMARY KEY CHECK (
                char_length(completion_id) BETWEEN 1 AND 256
            ),
            task_id TEXT NOT NULL REFERENCES read_investigation_run(task_id) ON DELETE CASCADE,
            run_attempt_count INTEGER NOT NULL CHECK (run_attempt_count BETWEEN 1 AND 3),
            payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
            state TEXT NOT NULL CHECK (
                state IN ('pending', 'sending', 'failed', 'delivered', 'abandoned')
            ),
            delivery_attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (
                delivery_attempt_count BETWEEN 0 AND 8
            ),
            next_attempt_at TIMESTAMPTZ NOT NULL,
            lease_token TEXT,
            lease_expires_at TIMESTAMPTZ,
            failure_reason TEXT CHECK (
                failure_reason IS NULL OR char_length(failure_reason) BETWEEN 1 AND 256
            ),
            retention_until TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            UNIQUE (task_id, run_attempt_count),
            CHECK (created_at <= updated_at AND updated_at <= retention_until),
            CHECK (
                (state = 'sending' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
                OR (state <> 'sending' AND lease_token IS NULL AND lease_expires_at IS NULL)
            )
        );
        CREATE INDEX ix_read_investigation_run_completion_due
            ON read_investigation_run_completion (next_attempt_at, completion_id)
            WHERE state IN ('pending', 'failed');
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM read_investigation_run
                 WHERE state IN ('cancel_requested', 'cancelled')
            ) OR EXISTS (SELECT 1 FROM read_investigation_run_progress)
              OR EXISTS (SELECT 1 FROM read_investigation_run_completion)
            THEN
                RAISE EXCEPTION 'interactive read investigation data blocks downgrade';
            END IF;
        END $$;

        DROP TABLE read_investigation_run_completion;
        DROP TABLE read_investigation_run_progress;
        DROP INDEX IF EXISTS ix_read_investigation_run_claim_lease;
        DROP INDEX IF EXISTS ix_read_investigation_run_retention;
        ALTER TABLE read_investigation_run
            DROP CONSTRAINT ck_read_investigation_run_lifecycle,
            DROP CONSTRAINT ck_read_investigation_run_state,
            DROP CONSTRAINT ck_read_investigation_run_task_id,
            DROP CONSTRAINT uq_read_investigation_run_task_id;
        ALTER TABLE read_investigation_run
            ADD CONSTRAINT ck_read_investigation_run_state CHECK (
                state IN ('claimed', 'running', 'completed', 'failed', 'expired')
            ),
            ADD CONSTRAINT ck_read_investigation_run_lifecycle CHECK (
                (state IN ('claimed', 'running')
                    AND lease_owner IS NOT NULL
                    AND lease_token IS NOT NULL
                    AND lease_expires_at IS NOT NULL
                    AND result IS NULL
                    AND usage IS NULL
                    AND failure_reason IS NULL
                    AND terminal_at IS NULL)
                OR (state = 'completed'
                    AND lease_owner IS NULL
                    AND lease_token IS NULL
                    AND lease_expires_at IS NULL
                    AND result IS NOT NULL
                    AND usage IS NOT NULL
                    AND failure_reason IS NULL
                    AND terminal_at = updated_at)
                OR (state IN ('failed', 'expired')
                    AND lease_owner IS NULL
                    AND lease_token IS NULL
                    AND lease_expires_at IS NULL
                    AND result IS NULL
                    AND usage IS NOT NULL
                    AND failure_reason IS NOT NULL
                    AND terminal_at = updated_at)
            );
        CREATE INDEX ix_read_investigation_run_claim_lease
            ON read_investigation_run (lease_expires_at, owner_principal_id, idempotency_key)
            WHERE state IN ('claimed', 'running');
        CREATE INDEX ix_read_investigation_run_retention
            ON read_investigation_run (retention_until, owner_principal_id, idempotency_key)
            WHERE state IN ('completed', 'failed', 'expired');
        ALTER TABLE read_investigation_run DROP COLUMN task_id;
        """
    )
