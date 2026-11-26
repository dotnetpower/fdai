-- Migration Revision: 20260706_0005
-- Down Revision: 20260705_0004
-- Owner: alembic
-- Extracted SQL Blocks: 4

-- Statement 1
CREATE EXTENSION IF NOT EXISTS vector;

-- Statement 2
CREATE TABLE IF NOT EXISTS t1_pattern_library (
            id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            signature                TEXT NOT NULL UNIQUE,
            rule_id                  TEXT NOT NULL,
            action_type              TEXT NOT NULL,
            params                   JSONB NOT NULL DEFAULT '{}'::jsonb,
            embedding                vector(384) NOT NULL,
            source_incident_id       TEXT NOT NULL,
            historical_success_rate  DOUBLE PRECISION NOT NULL DEFAULT 0.0
                CHECK (historical_success_rate >= 0.0
                       AND historical_success_rate <= 1.0),
            reuse_count              INTEGER NOT NULL DEFAULT 0
                CHECK (reuse_count >= 0),
            created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

-- Statement 3
CREATE INDEX idx_t1_pattern_library_rule_id ON t1_pattern_library(rule_id);

-- Statement 4
CREATE INDEX idx_t1_pattern_library_embedding_ivfflat
        ON t1_pattern_library
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100);
