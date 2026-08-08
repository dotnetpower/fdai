"""Add the Executor-owned transactional receipt publication outbox."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "executor_receipt_outbox_20260808"
down_revision: str | Sequence[str] | None = "executor_base_20260808"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "isolated-executor"
owned_tables = ("executor_receipt_outbox",)
rollback = {
    "strategy": "drop-executor-receipt-outbox",
    "restores": "executor_base_20260808",
}


def upgrade() -> None:
    op.create_table(
        "executor_receipt_outbox",
        sa.Column("receipt_id", sa.Uuid(), primary_key=True),
        sa.Column("partition_key", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
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
    op.drop_table("executor_receipt_outbox")
