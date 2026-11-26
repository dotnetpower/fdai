-- Migration Revision: 20260805_0072
-- Down Revision: 20260804_0071
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE conversation_image (
            principal_id TEXT NOT NULL,
            image_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            request_id TEXT NOT NULL,
            name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 128),
            media_type TEXT NOT NULL CHECK (
                media_type IN ('image/png', 'image/jpeg', 'image/gif', 'image/webp')
            ),
            content BYTEA NOT NULL CHECK (octet_length(content) BETWEEN 1 AND 4194304),
            content_sha256 CHAR(64) NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
            created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (principal_id, conversation_id, image_id),
            FOREIGN KEY (principal_id, conversation_id)
                REFERENCES conversation_record(principal_id, conversation_id)
                ON DELETE CASCADE
        );
        CREATE INDEX ix_conversation_image_history
            ON conversation_image (principal_id, conversation_id, created_at, image_id);
