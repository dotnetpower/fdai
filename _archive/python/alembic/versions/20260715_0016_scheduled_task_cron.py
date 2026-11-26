"""scheduled_task: persist strict five-field cron expressions

Revision ID: 20260715_0016
Revises: 20260714_0015
Create Date: 2026-07-15 13:16:11+00:00

Adds the optional cron expression used by schedule-triggered Workflows. Existing
interval schedules remain unchanged. Application boundary validation enforces
strict five-field cron syntax before a row is written.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260715_0016"
down_revision: str | None = "20260714_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE scheduled_task ADD COLUMN IF NOT EXISTS cron_expression TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE scheduled_task DROP COLUMN IF EXISTS cron_expression;")
