"""harden conversation image identity constraints

Revision ID: 20260805_0073
Revises: 20260805_0072
Create Date: 2026-08-05 00:00:01+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260805_0073"
down_revision: str | None = "20260805_0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE conversation_image
            ADD CONSTRAINT ck_conversation_image_id CHECK (
                image_id ~ '^att-[A-Za-z0-9-]{1,124}$'
            ),
            ADD CONSTRAINT ck_conversation_image_principal CHECK (
                btrim(principal_id) <> ''
            ),
            ADD CONSTRAINT ck_conversation_image_conversation CHECK (
                btrim(conversation_id) <> ''
            ),
            ADD CONSTRAINT ck_conversation_image_request CHECK (
                btrim(request_id) <> ''
            );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE conversation_image
            DROP CONSTRAINT IF EXISTS ck_conversation_image_request,
            DROP CONSTRAINT IF EXISTS ck_conversation_image_conversation,
            DROP CONSTRAINT IF EXISTS ck_conversation_image_principal,
            DROP CONSTRAINT IF EXISTS ck_conversation_image_id;
        """
    )
