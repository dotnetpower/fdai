"""schedule_dispatch_run: durable scheduler publication ledger

Revision ID: 143566f8b16b
Revises: 20260716_0022
Create Date: 2026-07-16 18:19:45.325426+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "143566f8b16b"
down_revision: str | None = "20260716_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE schedule_dispatch_run (
            run_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES scheduled_task(task_id) ON DELETE CASCADE,
            scheduled_for TIMESTAMPTZ NOT NULL,
            claimed_at TIMESTAMPTZ NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('claimed', 'published', 'failed', 'lost')),
            attempt INTEGER NOT NULL CHECK (attempt >= 1),
            completed_at TIMESTAMPTZ,
            error_kind TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX idx_schedule_dispatch_run_task_time "
        "ON schedule_dispatch_run(task_id, scheduled_for DESC);"
    )
    op.execute(
        "CREATE INDEX idx_schedule_dispatch_run_claimed "
        "ON schedule_dispatch_run(claimed_at) WHERE status = 'claimed';"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_schedule_dispatch_run_claimed;")
    op.execute("DROP INDEX IF EXISTS idx_schedule_dispatch_run_task_time;")
    op.execute("DROP TABLE IF EXISTS schedule_dispatch_run;")
