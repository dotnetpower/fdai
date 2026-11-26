-- Migration Revision: 20260716_0021
-- Down Revision: 20260716_0020
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE document_upload_session (
            upload_id UUID PRIMARY KEY,
            document_id UUID NOT NULL,
            version_id UUID NOT NULL,
            state TEXT NOT NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        );
        CREATE INDEX ix_document_upload_document
            ON document_upload_session (document_id, created_at DESC);

        CREATE TABLE document_version (
            document_id UUID NOT NULL,
            version_id UUID NOT NULL,
            upload_id UUID NOT NULL UNIQUE,
            state TEXT NOT NULL,
            active BOOLEAN NOT NULL DEFAULT FALSE,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (document_id, version_id),
            FOREIGN KEY (upload_id) REFERENCES document_upload_session(upload_id)
        );
        CREATE INDEX ix_document_version_history
            ON document_version (document_id, created_at DESC);
        CREATE UNIQUE INDEX uq_document_version_active
            ON document_version (document_id) WHERE active;
