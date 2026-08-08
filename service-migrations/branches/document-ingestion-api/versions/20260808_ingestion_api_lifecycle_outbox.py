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
    "strategy": "drop-api-outbox-and-revision-columns-after-worker-baseline",
    "restores": "ingestion_api_base_20260808",
    "requires": "document_worker_base_20260808",
}

_REQUIRED_WORKER_BASELINE = "document_worker_base_20260808"


def _require_worker_baseline() -> None:
    """Refuse to remove lifecycle columns while a worker consumer is deployed."""
    worker_head = (
        op.get_bind()
        .execute(sa.text("SELECT version_num FROM alembic_version_document_processing_worker"))
        .scalar_one_or_none()
    )
    if worker_head != _REQUIRED_WORKER_BASELINE:
        raise RuntimeError(
            "document-ingestion-api downgrade requires document-processing-worker "
            f"at {_REQUIRED_WORKER_BASELINE}; observed {worker_head!r}"
        )


def _require_no_unpublished_outbox() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("LOCK TABLE document_api_outbox IN ACCESS EXCLUSIVE MODE"))
    count = connection.execute(
        sa.text("SELECT count(*) FROM document_api_outbox WHERE published_at IS NULL")
    ).scalar_one()
    if int(count) != 0:
        raise RuntimeError(
            "document-ingestion-api downgrade is blocked while unpublished outbox rows exist"
        )


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
    op.execute(
        "REVOKE ALL PRIVILEGES ON TABLE document_api_outbox "
        "FROM PUBLIC, fdai_ingestion_worker, fdai_ingestion_cohost"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON TABLE document_api_outbox TO fdai_ingestion_api")
    op.execute(
        """
        CREATE FUNCTION enforce_document_lifecycle_transition_owner()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $lifecycle$
        DECLARE
            api_allowed BOOLEAN;
            worker_allowed BOOLEAN;
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
                OR (
                    OLD.state NOT IN ('deleting', 'deleted')
                    AND NEW.state = 'deleting'
                );
            worker_allowed :=
                (OLD.state = 'received' AND NEW.state = 'quarantined')
                OR (OLD.state = 'quarantined' AND NEW.state = 'scanning')
                OR (OLD.state = 'scanning' AND NEW.state = 'protection_check')
                OR (
                    OLD.state = 'protection_check'
                    AND NEW.state IN ('extracting', 'ready', 'held')
                )
                OR (OLD.state = 'extracting' AND NEW.state IN ('indexing', 'failed'))
                OR (
                    OLD.state = 'indexing'
                    AND NEW.state IN ('ready', 'ready_with_warnings', 'failed')
                )
                OR (OLD.state = 'deleting' AND NEW.state = 'deleted')
                OR (
                    TG_TABLE_NAME = 'document_version'
                    AND OLD.state = NEW.state
                    AND to_jsonb(OLD)->>'active' = 'true'
                    AND to_jsonb(NEW)->>'active' = 'false'
                );

            IF current_user = 'fdai_ingestion_api' AND NOT api_allowed THEN
                RAISE EXCEPTION
                    'fdai_ingestion_api does not own this lifecycle transition';
            ELSIF current_user = 'fdai_ingestion_worker' AND NOT worker_allowed THEN
                RAISE EXCEPTION
                    'fdai_ingestion_worker does not own this lifecycle transition';
            ELSIF current_user = 'fdai_ingestion_cohost'
                  AND NOT (api_allowed OR worker_allowed) THEN
                RAISE EXCEPTION
                    'fdai_ingestion_cohost does not own this lifecycle transition';
            END IF;
            RETURN NEW;
        END;
        $lifecycle$;

        CREATE TRIGGER document_upload_session_transition_owner
        BEFORE UPDATE ON document_upload_session
        FOR EACH ROW EXECUTE FUNCTION enforce_document_lifecycle_transition_owner();

        CREATE TRIGGER document_version_transition_owner
        BEFORE UPDATE ON document_version
        FOR EACH ROW EXECUTE FUNCTION enforce_document_lifecycle_transition_owner();
        """
    )


def downgrade() -> None:
    _require_worker_baseline()
    _require_no_unpublished_outbox()
    op.execute(
        """
        DROP TRIGGER document_version_transition_owner ON document_version;
        DROP TRIGGER document_upload_session_transition_owner ON document_upload_session;
        DROP FUNCTION enforce_document_lifecycle_transition_owner();
        """
    )
    op.execute("REVOKE ALL PRIVILEGES ON TABLE document_api_outbox FROM fdai_ingestion_api")
    op.drop_table("document_api_outbox")
    op.execute("UPDATE document_version SET payload = payload - 'revision'")
    op.execute("UPDATE document_upload_session SET payload = payload - 'revision'")
    op.drop_column("document_version", "revision")
    op.drop_column("document_upload_session", "revision")
