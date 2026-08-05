"""add independent conversation image expiry

Revision ID: 20260805_0074
Revises: 20260805_0073
Create Date: 2026-08-05 00:00:02+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260805_0074"
down_revision: str | None = "20260805_0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE conversation_image ADD COLUMN expires_at TIMESTAMPTZ;
        UPDATE conversation_image SET expires_at = created_at + INTERVAL '90 days';
        ALTER TABLE conversation_image
            ALTER COLUMN expires_at SET NOT NULL,
            ADD CONSTRAINT ck_conversation_image_expiry CHECK (expires_at > created_at);
        CREATE INDEX ix_conversation_image_expiry
            ON conversation_image (expires_at, principal_id, conversation_id, image_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_conversation_image_expiry;
        ALTER TABLE conversation_image
            DROP CONSTRAINT IF EXISTS ck_conversation_image_expiry,
            DROP COLUMN IF EXISTS expires_at;
        """
    )
