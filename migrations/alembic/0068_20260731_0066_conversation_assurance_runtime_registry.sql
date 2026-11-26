-- Migration Revision: 20260731_0066
-- Down Revision: 20260731_0065
-- Owner: alembic
-- Extracted SQL Blocks: 3

-- Statement 1
CREATE TABLE conversation_assurance_policy_runtime (
            principal_scope TEXT NOT NULL,
            target TEXT NOT NULL,
            candidate_id TEXT NOT NULL,
            policy_digest TEXT NOT NULL CHECK (char_length(policy_digest) = 64),
            policy_text TEXT NOT NULL CHECK (char_length(policy_text) BETWEEN 1 AND 2000),
            stage TEXT NOT NULL CHECK (stage IN (
                'shadow', 'canary_1', 'canary_5', 'canary_25', 'active', 'rolled_back'
            )),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (principal_scope, target)
        );

-- Statement 2
CREATE TABLE conversation_assurance_policy_publication (
            publication_key TEXT PRIMARY KEY,
            principal_scope TEXT NOT NULL,
            target TEXT NOT NULL,
            before_state JSONB,
            after_state JSONB,
            published_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

-- Statement 3
CREATE INDEX idx_assurance_policy_publication_scope_time ON conversation_assurance_policy_publication(principal_scope, published_at DESC);
