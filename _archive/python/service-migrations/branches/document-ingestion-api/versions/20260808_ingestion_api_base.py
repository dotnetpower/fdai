"""Adopt the verified legacy schema as the ingestion API migration baseline."""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "ingestion_api_base_20260808"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("document-ingestion-api",)
depends_on: str | Sequence[str] | None = None

migration_owner = "document-ingestion-api"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "delete-service-version-row",
    "restores": "legacy-alembic-version-authority",
}


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
