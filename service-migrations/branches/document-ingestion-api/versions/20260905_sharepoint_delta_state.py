"""Add durable SharePoint connector delta state."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "sharepoint_delta_state_20260905"
down_revision: str | Sequence[str] | None = "ingestion_api_outbox_20260808"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "document-ingestion-api"
owned_tables = (
    "document_connector_batch",
    "document_connector_cursor",
    "document_connector_item",
)
rollback = {
    "strategy": "drop-connector-state-after-delta-loop-stop",
    "restores": "ingestion_api_outbox_20260808",
}


def upgrade() -> None:
    op.create_table(
        "document_connector_cursor",
        sa.Column("connector_id", sa.Text(), primary_key=True),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "document_connector_batch",
        sa.Column("idempotency_key", sa.Text(), primary_key=True),
        sa.Column("connector_id", sa.Text(), nullable=False),
        sa.Column("collection_id", sa.Text(), nullable=False),
        sa.Column("access_descriptor_ref", sa.Text(), nullable=False),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "document_connector_item",
        sa.Column("connector_id", sa.Text(), nullable=False),
        sa.Column("source_item_id", sa.Text(), nullable=False),
        sa.Column("source_revision", sa.Text(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.Column("collection_id", sa.Text(), nullable=False),
        sa.Column("access_descriptor_ref", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("version_id", sa.Uuid(), nullable=True),
        sa.Column("deletion_pending", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("connector_id", "source_item_id"),
        sa.ForeignKeyConstraint(
            ["document_id", "version_id"],
            ["document_version.document_id", "document_version.version_id"],
        ),
        sa.CheckConstraint(
            "(document_id IS NULL) = (version_id IS NULL)",
            name="ck_document_connector_item_version_binding",
        ),
        sa.CheckConstraint("size_bytes >= 0", name="ck_document_connector_item_size"),
    )
    op.execute(
        "REVOKE ALL PRIVILEGES ON TABLE document_connector_cursor "
        "FROM PUBLIC, fdai_ingestion_worker, fdai_ingestion_cohost"
    )
    op.execute(
        "REVOKE ALL PRIVILEGES ON TABLE document_connector_batch "
        "FROM PUBLIC, fdai_ingestion_worker, fdai_ingestion_cohost"
    )
    op.execute(
        "REVOKE ALL PRIVILEGES ON TABLE document_connector_item "
        "FROM PUBLIC, fdai_ingestion_worker, fdai_ingestion_cohost"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON TABLE document_connector_cursor TO fdai_ingestion_api"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON TABLE document_connector_batch TO fdai_ingestion_api"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON TABLE document_connector_item TO fdai_ingestion_api"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_document_lifecycle_transition_owner()
        RETURNS TRIGGER LANGUAGE plpgsql AS $lifecycle$
        DECLARE api_allowed BOOLEAN; worker_allowed BOOLEAN;
        BEGIN
            IF NEW.revision <> OLD.revision + 1 THEN
                RAISE EXCEPTION 'document lifecycle revision must increment exactly once';
            END IF;
            IF NEW.payload->>'state' IS DISTINCT FROM NEW.state
               OR (NEW.payload->>'revision')::BIGINT IS DISTINCT FROM NEW.revision THEN
                RAISE EXCEPTION
                    'document lifecycle payload must match relational state and revision';
            END IF;
            api_allowed :=
                (OLD.state = 'created' AND NEW.state = 'uploading')
                OR (OLD.state = 'uploading' AND NEW.state IN ('received', 'held'))
                OR (OLD.state NOT IN ('deleting', 'deleted') AND NEW.state = 'deleting');
            worker_allowed :=
                (OLD.state = 'received' AND NEW.state = 'quarantined')
                OR (OLD.state = 'quarantined' AND NEW.state = 'scanning')
                OR (OLD.state = 'scanning' AND NEW.state = 'protection_check')
                OR (OLD.state = 'protection_check' AND NEW.state IN ('extracting', 'ready', 'held'))
                OR (OLD.state = 'extracting' AND NEW.state IN ('indexing', 'failed'))
                OR (
                    OLD.state = 'indexing'
                    AND NEW.state IN ('ready', 'ready_with_warnings', 'failed')
                )
                OR (OLD.state = 'deleting' AND NEW.state = 'deleted')
                OR (
                    TG_TABLE_NAME = 'document_version' AND OLD.state = NEW.state
                    AND (
                        (
                            to_jsonb(OLD)->>'active' = 'true'
                            AND to_jsonb(NEW)->>'active' = 'false'
                        )
                        OR (
                            OLD.payload->>'available' = 'true'
                            AND NEW.payload->>'available' = 'false'
                            AND NEW.payload->>'protection_state' = 'rights_managed_access_denied'
                        )
                    )
                );
            IF current_user = 'fdai_ingestion_api' AND NOT api_allowed THEN
                RAISE EXCEPTION 'fdai_ingestion_api does not own this lifecycle transition';
            ELSIF current_user = 'fdai_ingestion_worker' AND NOT worker_allowed THEN
                RAISE EXCEPTION 'fdai_ingestion_worker does not own this lifecycle transition';
            ELSIF current_user = 'fdai_ingestion_cohost'
                  AND NOT (api_allowed OR worker_allowed) THEN
                RAISE EXCEPTION 'fdai_ingestion_cohost does not own this lifecycle transition';
            END IF;
            RETURN NEW;
        END;
        $lifecycle$;
        """
    )


def downgrade() -> None:
    op.drop_table("document_connector_item")
    op.drop_table("document_connector_batch")
    op.drop_table("document_connector_cursor")
