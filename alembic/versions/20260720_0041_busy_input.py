"""durable busy-session input arbitration

Revision ID: 20260720_0041
Revises: 20260720_0040
Create Date: 2026-07-20 12:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260720_0041"
down_revision: str | None = "20260720_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE busy_session_state (
            session_id TEXT PRIMARY KEY CHECK (
                char_length(session_id) BETWEEN 1 AND 256
            ),
            owner_principal_id TEXT NOT NULL CHECK (
                char_length(owner_principal_id) BETWEEN 1 AND 256
            ),
            mode TEXT NOT NULL CHECK (mode IN ('queue', 'interrupt', 'steer')),
            active_turn_id TEXT CHECK (
                active_turn_id IS NULL
                OR char_length(active_turn_id) BETWEEN 1 AND 256
            ),
            revision BIGINT NOT NULL DEFAULT 1 CHECK (
                revision BETWEEN 1 AND 9223372036854775807
            ),
            next_sequence BIGINT NOT NULL DEFAULT 0 CHECK (
                next_sequence BETWEEN 0 AND 9223372036854775807
            ),
            CONSTRAINT uq_busy_session_owner_session
                UNIQUE (owner_principal_id, session_id)
        );

        CREATE TABLE busy_pending_input (
            session_id TEXT NOT NULL REFERENCES busy_session_state(session_id)
                ON DELETE CASCADE,
            input_id TEXT NOT NULL CHECK (
                char_length(input_id) BETWEEN 1 AND 256
            ),
            idempotency_key TEXT NOT NULL CHECK (
                char_length(idempotency_key) BETWEEN 1 AND 256
            ),
            principal_id TEXT NOT NULL CHECK (
                char_length(principal_id) BETWEEN 1 AND 256
            ),
            content TEXT NOT NULL CHECK (
                char_length(btrim(content)) > 0
                AND octet_length(content) <= 4000
            ),
            kind TEXT NOT NULL CHECK (
                kind IN ('prose', 'approval', 'denial', 'emergency_stop')
            ),
            received_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL CHECK (expires_at > received_at),
            sequence BIGINT NOT NULL CHECK (
                sequence BETWEEN 0 AND 9223372036854775807
            ),
            disposition TEXT NOT NULL CHECK (
                disposition IN ('queued', 'interrupting', 'steered', 'rejected')
            ),
            status TEXT NOT NULL CHECK (
                status IN ('pending', 'consumed', 'expired', 'rejected')
            ),
            consumed_at TIMESTAMPTZ,
            PRIMARY KEY (session_id, input_id),
            CONSTRAINT uq_busy_pending_session_idempotency
                UNIQUE (session_id, idempotency_key),
            CHECK (
                (disposition = 'rejected' AND status = 'rejected')
                OR (disposition <> 'rejected' AND status <> 'rejected')
            ),
            CHECK (
                (status = 'consumed' AND consumed_at IS NOT NULL)
                OR (status <> 'consumed' AND consumed_at IS NULL)
            )
        );
        CREATE UNIQUE INDEX uq_busy_pending_session_sequence
            ON busy_pending_input (session_id, sequence)
            WHERE disposition <> 'rejected';
        CREATE INDEX ix_busy_pending_session_sequence
            ON busy_pending_input (session_id, sequence)
            WHERE status = 'pending';
        CREATE INDEX ix_busy_pending_expiry
            ON busy_pending_input (expires_at, session_id, sequence)
            WHERE status = 'pending';
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_busy_pending_expiry;")
    op.execute("DROP INDEX IF EXISTS ix_busy_pending_session_sequence;")
    op.execute("DROP INDEX IF EXISTS uq_busy_pending_session_sequence;")
    op.execute("DROP TABLE IF EXISTS busy_pending_input;")
    op.execute("DROP TABLE IF EXISTS busy_session_state;")
