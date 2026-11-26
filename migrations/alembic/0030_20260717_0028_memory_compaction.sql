-- Migration Revision: 20260717_0028
-- Down Revision: 20260717_0027
-- Owner: alembic
-- Extracted SQL Blocks: 2

-- Statement 1
CREATE TABLE memory_compaction_candidate (
            candidate_id TEXT PRIMARY KEY,
            scope_kind TEXT NOT NULL CHECK (scope_kind IN ('resource-group', 'resource')),
            scope_ref TEXT NOT NULL,
            category TEXT NOT NULL CHECK (category IN (
                'preference', 'override-note', 'forbidden-action', 'runbook-hint'
            )),
            body TEXT NOT NULL,
            source_entry_ids UUID[] NOT NULL CHECK (cardinality(source_entry_ids) >= 2),
            source_refs TEXT[] NOT NULL CHECK (cardinality(source_refs) >= 2),
            proposed_by_agent TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            state TEXT NOT NULL CHECK (
                state IN ('draft', 'approved', 'rejected', 'promoted', 'rolled_back')
            ),
            reviewed_by TEXT,
            review_reason TEXT,
            reviewed_at TIMESTAMPTZ,
            promoted_entry_id UUID REFERENCES operator_memory(id),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (
                (state = 'draft' AND reviewed_by IS NULL AND reviewed_at IS NULL)
                OR (state <> 'draft' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)
            )
        );

-- Statement 2
CREATE INDEX idx_memory_compaction_state ON memory_compaction_candidate(state, created_at);
