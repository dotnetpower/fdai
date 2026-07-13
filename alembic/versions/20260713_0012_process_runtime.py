"""process runtime: current snapshots plus append-only transition journal

Revision ID: 20260713_0012
Revises: 20260713_0011
Create Date: 2026-07-13 00:00:01
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260713_0012"
down_revision: str | None = "20260713_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS process_runtime (
            process_id         TEXT PRIMARY KEY,
            workflow_ref       TEXT NOT NULL,
            workflow_version   TEXT NOT NULL,
            status             TEXT NOT NULL CHECK (status IN (
                'pending','running','waiting','compensating','compensated',
                'succeeded','failed','cancelled','timed_out'
            )),
            current_step       TEXT NOT NULL DEFAULT '',
            target_resource_id TEXT NOT NULL,
            started_at         TIMESTAMPTZ NOT NULL,
            updated_at         TIMESTAMPTZ NOT NULL,
            correlation_id     TEXT NOT NULL,
            revision           BIGINT NOT NULL DEFAULT 1 CHECK (revision >= 1)
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS process_event (
            seq             BIGSERIAL PRIMARY KEY,
            event_id        TEXT NOT NULL UNIQUE,
            process_id      TEXT NOT NULL REFERENCES process_runtime(process_id) ON DELETE CASCADE,
            kind            TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            recorded_at     TIMESTAMPTZ NOT NULL,
            correlation_id  TEXT NOT NULL,
            causation_id    TEXT,
            step_id         TEXT,
            attempt         INTEGER NOT NULL CHECK (attempt >= 1),
            payload         JSONB NOT NULL DEFAULT '{}'::jsonb
        );
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_process_event_process_seq "
        "ON process_event(process_id, seq);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_process_runtime_workflow_status "
        "ON process_runtime(workflow_ref, status);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS process_event CASCADE;")
    op.execute("DROP TABLE IF EXISTS process_runtime CASCADE;")
