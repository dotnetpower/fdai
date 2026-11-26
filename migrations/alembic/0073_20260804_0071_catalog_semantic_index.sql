-- Migration Revision: 20260804_0071
-- Down Revision: 20260803_0070
-- Owner: alembic
-- Extracted SQL Blocks: 3

-- Statement 1
CREATE EXTENSION IF NOT EXISTS vector;

-- Statement 2
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Statement 3
CREATE TABLE catalog_search_document (
            rule_id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            neighbor_ids TEXT[] NOT NULL,
            search_vector TSVECTOR NOT NULL,
            embedding vector(384) NOT NULL,
            content_hash CHAR(64) NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_catalog_search_rule_id_nonempty CHECK (length(rule_id) > 0),
            CONSTRAINT ck_catalog_search_text_nonempty CHECK (length(text) > 0),
            CONSTRAINT ck_catalog_search_content_hash CHECK (
                content_hash ~ '^[0-9a-f]{64}$'
            )
        );

        CREATE INDEX idx_catalog_search_document_lexical
            ON catalog_search_document USING gin (search_vector);
        CREATE INDEX idx_catalog_search_document_neighbors
            ON catalog_search_document USING gin (neighbor_ids);
        CREATE INDEX idx_catalog_search_document_embedding
            ON catalog_search_document
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100);
