"""Add native SharePoint connector item outcomes."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "native_sharepoint_connector_state_20260905"
down_revision: str | Sequence[str] | None = "power_platform_connector_state_20260905"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "document-ingestion-api"
owned_tables = ("document_connector_item",)
rollback = {
    "strategy": "drop-native-connector-outcome-columns-after-connector-stop",
    "restores": "power_platform_connector_state_20260905",
}


def upgrade() -> None:
    op.add_column(
        "document_connector_item",
        sa.Column(
            "ingestion_outcome",
            sa.Text(),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "document_connector_item",
        sa.Column("failure_code", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_document_connector_item_ingestion_outcome",
        "document_connector_item",
        "ingestion_outcome IN ('pending', 'accepted', 'rejected')",
    )
    op.create_check_constraint(
        "ck_document_connector_item_failure",
        "document_connector_item",
        "(ingestion_outcome = 'rejected') = (failure_code IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_document_connector_item_failure",
        "document_connector_item",
        type_="check",
    )
    op.drop_constraint(
        "ck_document_connector_item_ingestion_outcome",
        "document_connector_item",
        type_="check",
    )
    op.drop_column("document_connector_item", "failure_code")
    op.drop_column("document_connector_item", "ingestion_outcome")
