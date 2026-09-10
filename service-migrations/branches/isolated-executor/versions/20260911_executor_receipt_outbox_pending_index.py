"""Index pending isolated-Executor receipt publication work."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "executor_outbox_pending_index_20260911"
down_revision: str | Sequence[str] | None = "executor_runtime_role_20260808"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "isolated-executor"
owned_tables = ("executor_receipt_outbox",)
rollback = {
    "strategy": "drop-executor-receipt-outbox-pending-index",
    "restores": "executor_runtime_role_20260808",
}

_INDEX_NAME = "ix_executor_receipt_outbox_pending"


def upgrade() -> None:
    op.create_index(
        _INDEX_NAME,
        "executor_receipt_outbox",
        ["next_attempt_at", "created_at", "receipt_id"],
        unique=False,
        postgresql_where=sa.text("published_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="executor_receipt_outbox")
