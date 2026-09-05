"""Permit only deletion-axis progress while lifecycle state remains deleting."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "ingestion_lifecycle_axes_20260905"
down_revision: str | Sequence[str] | None = "native_sharepoint_connector_state_20260905"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "document-ingestion-api"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "restore-lifecycle-transition-owner-without-axis-progress",
    "restores": "power_platform_connector_state_20260905",
    "requires": "document-processing-worker-stopped",
}


def upgrade() -> None:
    """Allow the worker to advance only tombstone and purge-pending axes."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_document_lifecycle_transition_owner()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $lifecycle$
        DECLARE
            api_allowed BOOLEAN;
            worker_allowed BOOLEAN;
            worker_axis_allowed BOOLEAN;
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
            worker_axis_allowed :=
                OLD.state = 'deleting'
                AND NEW.state = 'deleting'
                AND NEW.payload->>'index_state' = 'tombstoned'
                AND NEW.payload->>'retention_state' IN ('tombstoned', 'purge_pending')
                AND (
                    OLD.payload
                        - 'revision' - 'index_state' - 'retention_state'
                        - 'updated_at' - 'active' - 'available'
                ) = (
                    NEW.payload
                        - 'revision' - 'index_state' - 'retention_state'
                        - 'updated_at' - 'active' - 'available'
                )
                AND (
                    TG_TABLE_NAME <> 'document_version'
                    OR (
                        to_jsonb(NEW)->>'active' = 'false'
                        AND NEW.payload->>'active' = 'false'
                        AND NEW.payload->>'available' = 'false'
                    )
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
                OR worker_axis_allowed
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
        """
    )


def downgrade() -> None:
    """Remove same-state deletion-axis progress from worker authority."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_document_lifecycle_transition_owner()
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
        """
    )
