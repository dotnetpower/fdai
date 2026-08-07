"""Adopt the verified legacy schema as the document worker migration baseline."""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "document_worker_base_20260808"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("document-processing-worker",)
depends_on: str | Sequence[str] | None = None

migration_owner = "document-processing-worker"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "delete-service-version-row",
    "restores": "legacy-alembic-version-authority",
}


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
