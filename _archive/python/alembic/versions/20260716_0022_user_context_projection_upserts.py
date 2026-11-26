"""user context projection upsert recovery queue

Revision ID: 20260716_0022
Revises: 20260716_0021
Create Date: 2026-07-16 18:10:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260716_0022"
down_revision: str | None = "20260716_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE user_context_projection_upsert_queue ("
        "projection_kind TEXT NOT NULL CHECK (projection_kind IN ("
        "'conversation_bundle', 'preference', 'memory', 'policy', "
        "'briefing_subscription', 'briefing_run', 'workflow_definition', "
        "'workflow_binding')), "
        "principal_id TEXT NOT NULL, "
        "record_id TEXT NOT NULL, "
        "available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
        "attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0), "
        "leased_until TIMESTAMPTZ, "
        "last_error TEXT, "
        "PRIMARY KEY (projection_kind, principal_id, record_id)"
        ");"
    )
    op.execute(
        "CREATE INDEX ix_user_context_projection_upsert_available "
        "ON user_context_projection_upsert_queue (available_at);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_context_projection_upsert_queue;")
