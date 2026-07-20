"""durable scheduled conversation continuations

Revision ID: 20260720_0044
Revises: 20260720_0043
Create Date: 2026-07-20 21:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260720_0044"
down_revision: str | None = "20260720_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE scheduled_task
            ADD COLUMN continuation_mode TEXT NOT NULL DEFAULT 'none'
                CHECK (continuation_mode IN ('none', 'origin_thread', 'dedicated_thread')),
            ADD COLUMN continuation_origin JSONB,
            ADD CONSTRAINT ck_scheduled_task_continuation_origin CHECK (
                (continuation_mode = 'none' AND continuation_origin IS NULL)
                OR (continuation_mode <> 'none' AND continuation_origin IS NOT NULL)
            );

        ALTER TABLE briefing_subscription
            ADD COLUMN continuation_mode TEXT NOT NULL DEFAULT 'none'
                CHECK (continuation_mode IN ('none', 'origin_thread', 'dedicated_thread')),
            ADD COLUMN continuation_origin JSONB,
            ADD COLUMN continuation_ttl_seconds INTEGER NOT NULL DEFAULT 604800
                CHECK (continuation_ttl_seconds BETWEEN 300 AND 31536000),
            ADD CONSTRAINT ck_briefing_subscription_continuation_origin CHECK (
                (continuation_mode = 'none' AND continuation_origin IS NULL)
                OR (continuation_mode <> 'none' AND continuation_origin IS NOT NULL)
            );

        ALTER TABLE briefing_run
            ADD COLUMN continuation_mode TEXT NOT NULL DEFAULT 'none'
                CHECK (continuation_mode IN ('none', 'origin_thread', 'dedicated_thread')),
            ADD COLUMN continuation_origin JSONB,
            ADD COLUMN result_digest TEXT CHECK (
                result_digest IS NULL OR char_length(result_digest) = 64
            ),
            ADD CONSTRAINT ck_briefing_run_continuation_metadata CHECK (
                (continuation_mode = 'none'
                    AND continuation_origin IS NULL AND result_digest IS NULL)
                OR (continuation_mode <> 'none'
                    AND continuation_origin IS NOT NULL AND result_digest IS NOT NULL)
            );

        CREATE TABLE scheduled_conversation_anchor (
            anchor_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            run_id TEXT NOT NULL UNIQUE,
            owner_principal_id TEXT NOT NULL,
            scope_ref TEXT NOT NULL,
            mode TEXT NOT NULL CHECK (mode IN ('origin_thread', 'dedicated_thread')),
            origin JSONB NOT NULL CHECK (jsonb_typeof(origin) = 'object'),
            result_digest TEXT NOT NULL CHECK (char_length(result_digest) = 64),
            result_summary TEXT NOT NULL CHECK (
                char_length(result_summary) BETWEEN 1 AND 100000
            ),
            evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (
                jsonb_typeof(evidence_refs) = 'array'
                AND jsonb_array_length(evidence_refs) <= 64
            ),
            observation_started_at TIMESTAMPTZ NOT NULL,
            observation_ended_at TIMESTAMPTZ NOT NULL CHECK (
                observation_ended_at >= observation_started_at
            ),
            created_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL CHECK (expires_at > created_at),
            state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'expired'))
        );
        CREATE INDEX ix_scheduled_conversation_anchor_owner
            ON scheduled_conversation_anchor (owner_principal_id, created_at DESC, anchor_id);
        CREATE INDEX ix_scheduled_conversation_anchor_expiry
            ON scheduled_conversation_anchor (expires_at, anchor_id)
            WHERE state = 'active';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE scheduled_conversation_anchor;
        ALTER TABLE briefing_run
            DROP COLUMN result_digest,
            DROP COLUMN continuation_origin,
            DROP COLUMN continuation_mode;
        ALTER TABLE briefing_subscription
            DROP COLUMN continuation_ttl_seconds,
            DROP COLUMN continuation_origin,
            DROP COLUMN continuation_mode;
        ALTER TABLE scheduled_task
            DROP COLUMN continuation_origin,
            DROP COLUMN continuation_mode;
        """
    )
