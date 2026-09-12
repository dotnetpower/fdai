"""Runtime skill proposal evidence references.

Revision ID: 20260912_0090
Revises: 20260831_0089
Create Date: 2026-09-12 00:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260912_0090"
down_revision: str | None = "20260831_0089"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE skill_proposal
        ADD COLUMN IF NOT EXISTS evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(evidence_refs) = 'array');
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE skill_proposal DROP COLUMN IF EXISTS evidence_refs;")
