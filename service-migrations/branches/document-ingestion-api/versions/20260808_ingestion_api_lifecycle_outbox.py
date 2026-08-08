"""Fence API lifecycle transitions and add its durable publication outbox."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ingestion_api_outbox_20260808"
down_revision: str | Sequence[str] | None = "ingestion_api_base_20260808"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "document-ingestion-api"
owned_tables = ("document_upload_session", "document_version", "document_api_outbox")
rollback = {
    "strategy": "drop-api-outbox-and-revision-columns",
    "restores": "ingestion_api_base_20260808",
}


def upgrade() -> None:
    op.add_column(
        "document_upload_session",
        sa.Column("revision", sa.BigInteger(), nullable=False, server_default="1"),
    )
    op.add_column(
        "document_version",
        sa.Column("revision", sa.BigInteger(), nullable=False, server_default="1"),
    )
    op.create_table(
        "document_api_outbox",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("partition_key", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("document_api_outbox")
    op.execute("UPDATE document_version SET payload = payload - 'revision'")
    op.execute("UPDATE document_upload_session SET payload = payload - 'revision'")
    op.drop_column("document_version", "revision")
    op.drop_column("document_upload_session", "revision")
