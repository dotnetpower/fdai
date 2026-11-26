"""channel_identity_link: explicit cross-channel identity relation

Revision ID: 20260717_0024
Revises: 20260717_0023
Create Date: 2026-07-17 05:00:00+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260717_0024"
down_revision: str | None = "20260717_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE channel_identity_link (
            link_id TEXT PRIMARY KEY,
            principal_id TEXT NOT NULL,
            first_channel_kind TEXT NOT NULL CHECK (
                first_channel_kind IN ('teams', 'slack', 'web')
            ),
            first_channel_id TEXT NOT NULL,
            first_sender_id TEXT NOT NULL,
            second_channel_kind TEXT NOT NULL CHECK (
                second_channel_kind IN ('teams', 'slack', 'web')
            ),
            second_channel_id TEXT NOT NULL,
            second_sender_id TEXT NOT NULL,
            approved_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            CHECK (first_channel_kind <> second_channel_kind)
        );
        """
    )
    op.execute(
        "CREATE INDEX idx_channel_identity_link_principal "
        "ON channel_identity_link(principal_id, created_at);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_channel_identity_link_principal;")
    op.execute("DROP TABLE IF EXISTS channel_identity_link;")
