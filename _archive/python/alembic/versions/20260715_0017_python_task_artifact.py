"""python_task_artifact: immutable governed Python source bundles

Revision ID: 20260715_0017
Revises: 20260715_0016
Create Date: 2026-07-15 13:30:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260715_0017"
down_revision: str | None = "20260715_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS python_task_artifact (
            artifact_ref TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            version TEXT NOT NULL,
            artifact_hash TEXT NOT NULL CHECK (artifact_hash ~ '^[0-9a-f]{64}$'),
            manifest JSONB NOT NULL,
            created_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (task_id, version)
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS python_task_artifact;")
