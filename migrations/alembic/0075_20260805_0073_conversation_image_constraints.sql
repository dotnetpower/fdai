-- Migration Revision: 20260805_0073
-- Down Revision: 20260805_0072
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
ALTER TABLE conversation_image
            ADD CONSTRAINT ck_conversation_image_id CHECK (
                image_id ~ '^att-[A-Za-z0-9-]{1,124}$'
            ),
            ADD CONSTRAINT ck_conversation_image_principal CHECK (
                btrim(principal_id) <> ''
            ),
            ADD CONSTRAINT ck_conversation_image_conversation CHECK (
                btrim(conversation_id) <> ''
            ),
            ADD CONSTRAINT ck_conversation_image_request CHECK (
                btrim(request_id) <> ''
            );
