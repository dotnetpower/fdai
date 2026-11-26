"""conversation assurance policy artifact

Revision ID: 20260731_0065
Revises: 20260731_0064
Create Date: 2026-07-31 00:00:03+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260731_0065"
down_revision: str | None = "20260731_0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE conversation_assurance_policy_candidate ADD COLUMN policy_text TEXT")
    op.execute(
        "ALTER TABLE conversation_assurance_policy_candidate "
        "ADD CONSTRAINT ck_assurance_policy_candidate_text "
        "CHECK (policy_text IS NULL OR char_length(policy_text) BETWEEN 1 AND 2000)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE conversation_assurance_policy_candidate "
        "DROP CONSTRAINT IF EXISTS ck_assurance_policy_candidate_text"
    )
    op.execute(
        "ALTER TABLE conversation_assurance_policy_candidate DROP COLUMN IF EXISTS policy_text"
    )
