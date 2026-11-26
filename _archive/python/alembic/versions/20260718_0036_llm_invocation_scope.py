"""add explicit LLM invocation usage scope

Revision ID: 20260718_0036
Revises: 20260718_0035
Create Date: 2026-07-18 00:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260718_0036"
down_revision: str | None = "20260718_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE llm_invocation
            ADD COLUMN usage_scope TEXT NOT NULL DEFAULT 'control_plane'
            CHECK (usage_scope IN ('control_plane', 'operator_chat'));
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE llm_invocation DROP COLUMN usage_scope;")
