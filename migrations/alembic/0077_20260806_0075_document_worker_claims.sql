-- Migration Revision: 20260806_0075
-- Down Revision: 20260805_0074
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE document_worker_claim (
            upload_id UUID NOT NULL REFERENCES document_upload_session(upload_id)
                ON DELETE CASCADE,
            stage TEXT NOT NULL CHECK (stage IN (
                'received_replay', 'inspection', 'protection_replay',
                'safety_decision', 'indexing'
            )),
            owner TEXT NOT NULL CHECK (char_length(owner) BETWEEN 1 AND 256),
            attempt_id UUID NOT NULL,
            revision INTEGER NOT NULL CHECK (revision >= 1),
            status TEXT NOT NULL CHECK (status IN ('active', 'completed', 'released')),
            claimed_at TIMESTAMPTZ NOT NULL,
            lease_expires_at TIMESTAMPTZ NOT NULL,
            finished_at TIMESTAMPTZ,
            PRIMARY KEY (upload_id, stage),
            CHECK (lease_expires_at > claimed_at),
            CHECK (
                (status = 'active' AND finished_at IS NULL)
                OR (status IN ('completed', 'released') AND finished_at IS NOT NULL)
            )
        );

        CREATE INDEX ix_document_worker_claim_active_lease
            ON document_worker_claim (lease_expires_at, upload_id, stage)
            WHERE status = 'active';
