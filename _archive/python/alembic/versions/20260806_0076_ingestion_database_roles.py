"""add least-privilege ingestion API and worker database roles

Revision ID: 20260806_0076
Revises: 20260806_0075
Create Date: 2026-08-06 09:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260806_0076"
down_revision: str | None = "20260806_0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fdai_ingestion_api') THEN
                CREATE ROLE fdai_ingestion_api NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fdai_ingestion_worker') THEN
                CREATE ROLE fdai_ingestion_worker NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fdai_ingestion_cohost') THEN
                CREATE ROLE fdai_ingestion_cohost NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
            END IF;
        END
        $$;

        GRANT fdai_ingestion_api, fdai_ingestion_worker, fdai_ingestion_cohost TO CURRENT_USER;
        GRANT USAGE ON SCHEMA public
            TO fdai_ingestion_api, fdai_ingestion_worker, fdai_ingestion_cohost;

        GRANT SELECT, INSERT, UPDATE
            ON document_upload_session, document_version
            TO fdai_ingestion_api;
        GRANT SELECT, INSERT, UPDATE, DELETE ON state_kv TO fdai_ingestion_api;
        GRANT SELECT, INSERT ON audit_log TO fdai_ingestion_api;
        GRANT SELECT, DELETE ON knowledge_chunk TO fdai_ingestion_api;

        GRANT SELECT, UPDATE
            ON document_upload_session, document_version
            TO fdai_ingestion_worker;
        GRANT SELECT, INSERT, UPDATE, DELETE
            ON document_worker_claim, knowledge_chunk, state_kv
            TO fdai_ingestion_worker;
        GRANT SELECT, INSERT ON audit_log TO fdai_ingestion_worker;

        GRANT SELECT, INSERT, UPDATE, DELETE
            ON document_upload_session, document_version, document_worker_claim,
               knowledge_chunk, state_kv
            TO fdai_ingestion_cohost;
        GRANT SELECT, INSERT ON audit_log TO fdai_ingestion_cohost;

        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public
            TO fdai_ingestion_api, fdai_ingestion_worker, fdai_ingestion_cohost;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP OWNED BY fdai_ingestion_api;
        DROP OWNED BY fdai_ingestion_worker;
        DROP OWNED BY fdai_ingestion_cohost;
        REVOKE fdai_ingestion_api, fdai_ingestion_worker, fdai_ingestion_cohost
            FROM CURRENT_USER;
        DROP ROLE IF EXISTS fdai_ingestion_api;
        DROP ROLE IF EXISTS fdai_ingestion_worker;
        DROP ROLE IF EXISTS fdai_ingestion_cohost;
        """
    )
