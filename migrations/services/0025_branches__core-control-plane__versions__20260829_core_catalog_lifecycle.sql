-- Migration Revision: core_catalog_lifecycle_20260829
-- Down Revision: core_background_task_progress_order_20260829
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
ALTER TABLE learned_action
            ADD COLUMN IF NOT EXISTS catalog_version TEXT;
        UPDATE learned_action
           SET catalog_version = 'legacy'
         WHERE catalog_version IS NULL;
        ALTER TABLE learned_action
            ALTER COLUMN catalog_version SET NOT NULL,
            ALTER COLUMN catalog_version SET DEFAULT 'legacy';
        ALTER TABLE learned_action
            DROP CONSTRAINT IF EXISTS learned_action_action_signature_key;
        DROP INDEX IF EXISTS learned_action_action_signature_key;
        CREATE UNIQUE INDEX IF NOT EXISTS learned_action_catalog_signature_key
            ON learned_action (catalog_version, action_signature);
        CREATE INDEX IF NOT EXISTS idx_learned_action_rule_catalog
            ON learned_action (rule_id, catalog_version);

        ALTER TABLE t2_cache
            ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
        UPDATE t2_cache
           SET expires_at = created_at + INTERVAL '1 hour'
         WHERE expires_at IS NULL;
        ALTER TABLE t2_cache
            ALTER COLUMN expires_at SET NOT NULL,
            ALTER COLUMN expires_at SET DEFAULT (NOW() + INTERVAL '1 hour');
        CREATE INDEX IF NOT EXISTS idx_t2_cache_expires_at
            ON t2_cache (expires_at);
