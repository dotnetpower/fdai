-- Migration Revision: 20260805_0074
-- Down Revision: 20260805_0073
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
ALTER TABLE conversation_image ADD COLUMN expires_at TIMESTAMPTZ;
        UPDATE conversation_image SET expires_at = created_at + INTERVAL '90 days';
        ALTER TABLE conversation_image
            ALTER COLUMN expires_at SET NOT NULL,
            ADD CONSTRAINT ck_conversation_image_expiry CHECK (expires_at > created_at);
        CREATE INDEX ix_conversation_image_expiry
            ON conversation_image (expires_at, principal_id, conversation_id, image_id);
