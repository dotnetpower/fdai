"""channel_pairing_request: durable channel sender pairing

Revision ID: 20260717_0023
Revises: 143566f8b16b
Create Date: 2026-07-17 04:40:00+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260717_0023"
down_revision: str | None = "143566f8b16b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE channel_pairing_request (
            channel_kind TEXT NOT NULL CHECK (channel_kind IN ('teams', 'slack', 'web')),
            channel_id TEXT NOT NULL,
            sender_id TEXT NOT NULL,
            code_digest TEXT NOT NULL CHECK (length(code_digest) = 64),
            created_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL CHECK (expires_at > created_at),
            approved_principal_id TEXT,
            approved_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (channel_kind, channel_id, sender_id),
            CHECK ((approved_principal_id IS NULL) = (approved_at IS NULL))
        );
        """
    )
    op.execute(
        "CREATE INDEX idx_channel_pairing_pending "
        "ON channel_pairing_request(channel_kind, expires_at) "
        "WHERE approved_principal_id IS NULL;"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_channel_pairing_pending;")
    op.execute("DROP TABLE IF EXISTS channel_pairing_request;")
