-- Migration Revision: 20260717_0026
-- Down Revision: 20260717_0025
-- Owner: alembic
-- Extracted SQL Blocks: 2

-- Statement 1
CREATE TABLE skill_proposal (
            proposal_id TEXT PRIMARY KEY,
            skill_name TEXT NOT NULL,
            content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
            markdown BYTEA NOT NULL,
            proposed_by_agent TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            state TEXT NOT NULL CHECK (
                state IN ('draft', 'approved', 'rejected', 'materialized')
            ),
            reviewed_by TEXT,
            review_reason TEXT,
            reviewed_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (
                (state = 'draft' AND reviewed_by IS NULL AND reviewed_at IS NULL)
                OR (state <> 'draft' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)
            )
        );

-- Statement 2
CREATE INDEX idx_skill_proposal_state ON skill_proposal(state, created_at);
