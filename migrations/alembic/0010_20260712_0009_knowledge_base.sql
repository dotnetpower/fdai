-- Migration Revision: 20260712_0009
-- Down Revision: 20260709_0001
-- Owner: alembic
-- Extracted SQL Blocks: 4

-- Statement 1
CREATE EXTENSION IF NOT EXISTS vector;

-- Statement 2
CREATE TABLE IF NOT EXISTS knowledge_chunk (
            chunk_id     TEXT PRIMARY KEY,
            doc_id       TEXT NOT NULL,
            text         TEXT NOT NULL,
            source_ref   TEXT NOT NULL,
            embedding    vector(384) NOT NULL,
            metadata     JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

-- Statement 3
CREATE INDEX idx_knowledge_chunk_doc_id ON knowledge_chunk(doc_id);

-- Statement 4
CREATE INDEX idx_knowledge_chunk_embedding
            ON knowledge_chunk
         USING ivfflat (embedding vector_cosine_ops)
          WITH (lists = 100);
