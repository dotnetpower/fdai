-- Migration Revision: 20260814_0083
-- Down Revision: 20260814_0082
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
ALTER TABLE browser_evidence_artifact
            ADD COLUMN legal_hold BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN legal_hold_ref TEXT,
            ADD COLUMN legal_hold_at TIMESTAMPTZ,
            ADD CONSTRAINT ck_browser_evidence_legal_hold_consistent CHECK (
                (legal_hold = TRUE
                 AND legal_hold_ref IS NOT NULL
                 AND length(legal_hold_ref) BETWEEN 1 AND 512
                 AND legal_hold_at IS NOT NULL)
                OR
                (legal_hold = FALSE
                 AND legal_hold_ref IS NULL
                 AND legal_hold_at IS NULL)
            );
        CREATE INDEX browser_evidence_artifact_purge_idx
            ON browser_evidence_artifact (expires_at, artifact_id)
            WHERE legal_hold = FALSE;
