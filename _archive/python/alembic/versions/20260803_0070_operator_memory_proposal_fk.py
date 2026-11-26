"""link materialized operator-memory proposals to retained entries

Revision ID: 20260803_0070
Revises: 20260801_0069
Create Date: 2026-08-03 00:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260803_0070"
down_revision: str | None = "20260801_0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "fk_operator_memory_proposal_materialized_entry"


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE operator_memory_proposal
            ADD CONSTRAINT {_CONSTRAINT}
            FOREIGN KEY (materialized_entry_id)
            REFERENCES operator_memory(id)
            ON DELETE RESTRICT
            NOT VALID;
        ALTER TABLE operator_memory_proposal
            VALIDATE CONSTRAINT {_CONSTRAINT};
        """
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE operator_memory_proposal DROP CONSTRAINT IF EXISTS {_CONSTRAINT};")
