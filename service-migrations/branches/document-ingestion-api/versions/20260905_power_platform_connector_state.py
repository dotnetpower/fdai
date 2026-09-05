"""Extend native connector state; retain the published revision id for compatibility."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "power_platform_connector_state_20260905"
down_revision: str | Sequence[str] | None = "sharepoint_delta_state_20260905"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "document-ingestion-api"
owned_tables = ("document_connector_cancellation", "document_connector_item")
rollback = {
    "strategy": "drop-power-platform-ordering-columns-after-connector-stop",
    "restores": "sharepoint_delta_state_20260905",
}


def upgrade() -> None:
    op.add_column(
        "document_connector_item",
        sa.Column("source_sequence", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "document_connector_item",
        sa.Column("bound_source_revision", sa.Text(), nullable=True),
    )
    op.add_column(
        "document_connector_item",
        sa.Column("content_sha256", sa.Text(), nullable=True),
    )
    op.create_table(
        "document_connector_cancellation",
        sa.Column("connector_id", sa.Text(), nullable=False),
        sa.Column("source_item_id", sa.Text(), nullable=False),
        sa.Column("source_revision", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("connector_id", "source_item_id", "source_revision"),
        sa.CheckConstraint(
            "status IN ('pending', 'completed')",
            name="ck_document_connector_cancellation_status",
        ),
    )
    op.execute(
        "REVOKE ALL PRIVILEGES ON TABLE document_connector_cancellation "
        "FROM PUBLIC, fdai_ingestion_worker, fdai_ingestion_cohost"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON TABLE document_connector_cancellation "
        "TO fdai_ingestion_api"
    )
    op.execute(
        "UPDATE document_connector_item "
        "SET bound_source_revision = source_revision "
        "WHERE document_id IS NOT NULL"
    )
    op.create_check_constraint(
        "ck_document_connector_item_revision_binding",
        "document_connector_item",
        "(document_id IS NULL) = (bound_source_revision IS NULL)",
    )
    op.create_check_constraint(
        "ck_document_connector_item_sequence",
        "document_connector_item",
        "source_sequence IS NULL OR source_sequence >= 0",
    )
    op.create_check_constraint(
        "ck_document_connector_item_content_sha256",
        "document_connector_item",
        "content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_document_connector_item_content_sha256",
        "document_connector_item",
        type_="check",
    )
    op.drop_constraint(
        "ck_document_connector_item_sequence",
        "document_connector_item",
        type_="check",
    )
    op.drop_constraint(
        "ck_document_connector_item_revision_binding",
        "document_connector_item",
        type_="check",
    )
    op.drop_column("document_connector_item", "content_sha256")
    op.drop_column("document_connector_item", "bound_source_revision")
    op.drop_column("document_connector_item", "source_sequence")
    op.drop_table("document_connector_cancellation")
