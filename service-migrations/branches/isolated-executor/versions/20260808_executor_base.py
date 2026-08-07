"""Adopt the verified legacy schema as the isolated Executor migration baseline."""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "executor_base_20260808"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("isolated-executor",)
depends_on: str | Sequence[str] | None = None

migration_owner = "isolated-executor"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "delete-service-version-row",
    "restores": "legacy-alembic-version-authority",
}


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
