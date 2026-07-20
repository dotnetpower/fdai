"""programmatic pipeline receipts and aggregate results

Revision ID: 20260720_0046
Revises: 20260720_0045
Create Date: 2026-07-20 23:15:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260720_0046"
down_revision: str | None = "20260720_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE programmatic_pipeline_run (
            idempotency_key TEXT PRIMARY KEY,
            run_id TEXT NOT NULL UNIQUE,
            source_digest TEXT NOT NULL CHECK (char_length(source_digest) = 64),
            status TEXT NOT NULL CHECK (
                status IN (
                    'succeeded', 'rejected', 'failed',
                    'timed_out', 'cancelled', 'incomplete'
                )
            ),
            result JSONB NOT NULL CHECK (jsonb_typeof(result) = 'object'),
            completed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX programmatic_pipeline_run_completed_idx
            ON programmatic_pipeline_run (completed_at DESC, run_id);
        CREATE TABLE programmatic_pipeline_call (
            run_id TEXT NOT NULL,
            call_id TEXT NOT NULL,
            sequence INTEGER NOT NULL CHECK (sequence > 0),
            tool_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('succeeded', 'rejected', 'failed')),
            receipt JSONB NOT NULL CHECK (jsonb_typeof(receipt) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (run_id, call_id),
            UNIQUE (run_id, sequence)
        );
        CREATE INDEX programmatic_pipeline_call_tool_idx
            ON programmatic_pipeline_call (tool_id, recorded_at DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE programmatic_pipeline_call;
        DROP TABLE programmatic_pipeline_run;
        """
    )
