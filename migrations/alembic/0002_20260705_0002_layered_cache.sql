-- Migration Revision: 20260705_0002
-- Down Revision: 20260705_0001
-- Owner: alembic
-- Extracted SQL Blocks: 9

-- Statement 1
CREATE EXTENSION IF NOT EXISTS vector;

-- Statement 2
CREATE TABLE IF NOT EXISTS learned_action (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            rule_id          TEXT NOT NULL,
            action_signature TEXT NOT NULL UNIQUE,
            action_payload   JSONB NOT NULL,
            success_count    INTEGER NOT NULL DEFAULT 0,
            rollback_count   INTEGER NOT NULL DEFAULT 0,
            last_used_at     TIMESTAMPTZ,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

-- Statement 3
CREATE INDEX idx_learned_action_rule_id ON learned_action(rule_id);

-- Statement 4
CREATE TABLE IF NOT EXISTS ontology_embedding (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            resource_ref TEXT NOT NULL REFERENCES ontology_resource(id) ON DELETE CASCADE,
            model        TEXT NOT NULL,
            embedding    vector(1536) NOT NULL,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

-- Statement 5
CREATE INDEX idx_ontology_embedding_resource_ref ON ontology_embedding(resource_ref);

-- Statement 6
CREATE INDEX idx_ontology_embedding_hnsw
        ON ontology_embedding USING hnsw (embedding vector_cosine_ops);

-- Statement 7
CREATE TABLE IF NOT EXISTS t2_cache (
            id              UUID NOT NULL DEFAULT gen_random_uuid(),
            catalog_version TEXT NOT NULL,
            input_hash      TEXT NOT NULL,
            output          JSONB NOT NULL,
            model           TEXT NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (catalog_version, id)
        ) PARTITION BY LIST (catalog_version);

-- Statement 8
CREATE TABLE IF NOT EXISTS t2_cache_default PARTITION OF t2_cache DEFAULT;

-- Statement 9
CREATE INDEX idx_t2_cache_input_hash ON t2_cache (catalog_version, input_hash);
