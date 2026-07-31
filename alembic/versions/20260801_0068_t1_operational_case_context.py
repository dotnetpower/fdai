"""T1 operational case context

Revision ID: 20260801_0068
Revises: 20260801_0067
Create Date: 2026-08-01 00:00:01+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260801_0068"
down_revision: str | None = "20260801_0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE t1_pattern_library
            ADD COLUMN operational_case JSONB,
            ADD CONSTRAINT ck_t1_pattern_operational_case_object CHECK (
                operational_case IS NULL OR jsonb_typeof(operational_case) = 'object'
            );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE t1_pattern_library
            DROP CONSTRAINT ck_t1_pattern_operational_case_object,
            DROP COLUMN operational_case;
        """
    )
