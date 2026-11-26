"""Add native SharePoint full-resync epochs."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "native_sharepoint_resync_state_20260905"
down_revision: str | Sequence[str] | None = "native_sharepoint_connector_state_20260905"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "document-ingestion-api"
owned_tables = ("document_connector_item",)
rollback = {
    "strategy": "drop-resync-epoch-after-native-connector-stop",
    "restores": "native_sharepoint_connector_state_20260905",
}


def upgrade() -> None:
    op.add_column(
        "document_connector_item",
        sa.Column("sync_epoch", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_document_connector_item_sync_epoch",
        "document_connector_item",
        "sync_epoch >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_document_connector_item_sync_epoch",
        "document_connector_item",
        type_="check",
    )
    op.drop_column("document_connector_item", "sync_epoch")
