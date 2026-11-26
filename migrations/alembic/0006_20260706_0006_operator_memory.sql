-- Migration Revision: 20260706_0006
-- Down Revision: 20260706_0005
-- Owner: alembic
-- Extracted SQL Blocks: 2

-- Statement 1
CREATE TABLE IF NOT EXISTS operator_memory (
            id             UUID PRIMARY KEY,
            scope_kind     TEXT NOT NULL
                CHECK (scope_kind IN ('resource-group', 'resource')),
            scope_ref      TEXT NOT NULL
                CHECK (btrim(scope_ref) <> ''),
            category       TEXT NOT NULL
                CHECK (category IN (
                    'preference',
                    'override-note',
                    'forbidden-action',
                    'runbook-hint'
                )),
            body           TEXT NOT NULL
                CHECK (btrim(body) <> ''),
            source_event   TEXT NOT NULL,
            source_ref     TEXT NOT NULL,
            author         TEXT NOT NULL
                CHECK (btrim(author) <> ''),
            approved_by    TEXT NOT NULL
                CHECK (btrim(approved_by) <> ''),
            created_at     TIMESTAMPTZ NOT NULL,
            superseded_by  UUID NULL REFERENCES operator_memory(id),
            ttl_seconds    INTEGER NULL
                CHECK (ttl_seconds IS NULL OR ttl_seconds > 0),
            CONSTRAINT operator_memory_distinct_approver
                CHECK (
                    lower(btrim(author)) <> lower(btrim(approved_by))
                )
        );

-- Statement 2
CREATE INDEX idx_operator_memory_scope
        ON operator_memory (scope_kind, scope_ref);
