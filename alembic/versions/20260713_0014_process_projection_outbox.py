"""process projection outbox: durable ontology projection retries

Revision ID: 20260713_0014
Revises: 20260713_0013
Create Date: 2026-07-13 00:00:03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260713_0014"
down_revision: str | None = "20260713_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS process_projection_outbox (
            event_id      TEXT PRIMARY KEY REFERENCES process_event(event_id) ON DELETE CASCADE,
            process_id    TEXT NOT NULL REFERENCES process_runtime(process_id) ON DELETE CASCADE,
            attempts      INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            available_at  TIMESTAMPTZ NOT NULL,
            leased_until  TIMESTAMPTZ,
            last_error    TEXT
        );
    """)
    op.execute("""
        INSERT INTO process_projection_outbox (event_id, process_id, available_at)
        SELECT event_id, process_id, recorded_at FROM process_event
        ON CONFLICT (event_id) DO NOTHING;
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_process_projection_outbox_available "
        "ON process_projection_outbox(available_at, event_id);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS process_projection_outbox CASCADE;")