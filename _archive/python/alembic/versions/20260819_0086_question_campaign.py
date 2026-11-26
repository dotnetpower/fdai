"""question space campaign and case-attempt ledgers

Revision ID: 20260819_0086
Revises: 20260817_0085
Create Date: 2026-08-19 00:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260819_0086"
down_revision: str | None = "20260817_0085"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Retain the legacy head while Core owns the forward schema transition."""
    op.execute("SELECT 1")


def downgrade() -> None:
    """Keep Core-owned question campaign tables outside legacy rollback."""
    op.execute("SELECT 1")
