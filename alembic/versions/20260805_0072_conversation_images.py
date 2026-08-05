"""add principal-scoped conversation image storage

Revision ID: 20260805_0072
Revises: 20260804_0071
Create Date: 2026-08-05 00:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260805_0072"
down_revision: str | None = "20260804_0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE conversation_image (
            principal_id TEXT NOT NULL,
            image_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            request_id TEXT NOT NULL,
            name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 128),
            media_type TEXT NOT NULL CHECK (
                media_type IN ('image/png', 'image/jpeg', 'image/gif', 'image/webp')
            ),
            content BYTEA NOT NULL CHECK (octet_length(content) BETWEEN 1 AND 4194304),
            content_sha256 CHAR(64) NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
            created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (principal_id, conversation_id, image_id),
            FOREIGN KEY (principal_id, conversation_id)
                REFERENCES conversation_record(principal_id, conversation_id)
                ON DELETE CASCADE
        );
        CREATE INDEX ix_conversation_image_history
            ON conversation_image (principal_id, conversation_id, created_at, image_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS conversation_image;")
