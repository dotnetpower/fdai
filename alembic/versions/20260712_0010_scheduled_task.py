"""scheduled_task: persistent store for operator-created recurring tasks

Revision ID: 20260712_0010
Revises: 20260712_0009
Create Date: 2026-07-12 00:00:00

Backs :class:`~fdai.delivery.persistence.postgres_scheduler_store.PostgresScheduleStore`
with a persistent table so schedules survive a process restart and are
shared between the operator console (create / list / cancel) and the
Container Apps Job cron that drives ``SchedulerService.run_once``. The
in-memory :class:`~fdai.core.scheduler.store.InMemoryScheduleStore` mirrors
the same ``ScheduleStore`` contract for unit tests (P2-6).

Columns mirror :class:`~fdai.core.scheduler.models.ScheduledTask` exactly:
``task_id`` (PK), ``name``, ``interval_seconds`` (> 0), ``event_type``,
``created_by`` (audit / RBAC scope), ``event_payload`` (JSONB),
``resource_ref``, ``enabled``, ``start_at``, ``last_run``, plus a server
``created_at``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260712_0010"
down_revision: str | None = "20260712_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_task (
            task_id          TEXT PRIMARY KEY,
            name             TEXT NOT NULL,
            interval_seconds DOUBLE PRECISION NOT NULL CHECK (interval_seconds > 0),
            event_type       TEXT NOT NULL,
            created_by       TEXT NOT NULL,
            event_payload    JSONB NOT NULL DEFAULT '{}'::jsonb,
            resource_ref     TEXT,
            enabled          BOOLEAN NOT NULL DEFAULT TRUE,
            start_at         TIMESTAMPTZ,
            last_run         TIMESTAMPTZ,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    # The scheduler scans enabled tasks every tick; index the flag.
    op.execute("CREATE INDEX idx_scheduled_task_enabled ON scheduled_task(enabled) WHERE enabled;")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_scheduled_task_enabled;")
    op.execute("DROP TABLE IF EXISTS scheduled_task;")
