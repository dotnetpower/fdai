"""answer preference profile

Revision ID: 20260717_0033
Revises: 20260717_0032
Create Date: 2026-07-17 02:43:08.582293+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260717_0033"
down_revision: str | None = "20260717_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE user_preference
            ADD COLUMN answer_detail TEXT NOT NULL DEFAULT 'standard'
                CHECK (answer_detail IN ('brief', 'standard', 'deep')),
            ADD COLUMN answer_format TEXT NOT NULL DEFAULT 'prose'
                CHECK (answer_format IN (
                    'prose', 'bullets', 'numbered_steps', 'table', 'checklist', 'mixed'
                )),
            ADD COLUMN answer_preferences_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN answer_intent_detail JSONB NOT NULL DEFAULT '{}'::jsonb
                CHECK (jsonb_typeof(answer_intent_detail) = 'object'),
            ADD COLUMN answer_intent_format JSONB NOT NULL DEFAULT '{}'::jsonb
                CHECK (jsonb_typeof(answer_intent_format) = 'object');
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE user_preference
            DROP COLUMN answer_intent_format,
            DROP COLUMN answer_intent_detail,
            DROP COLUMN answer_preferences_enabled,
            DROP COLUMN answer_format,
            DROP COLUMN answer_detail;
        """
    )
