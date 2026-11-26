-- Migration Revision: 20260814_0082
-- Down Revision: 20260813_0081
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
DO $$
        DECLARE
            identity_constraint TEXT;
        BEGIN
            SELECT constraint_record.conname
              INTO identity_constraint
              FROM pg_constraint AS constraint_record
             WHERE constraint_record.conrelid = 'llm_invocation'::regclass
               AND constraint_record.contype = 'u'
               AND ARRAY(
                SELECT attribute.attname::TEXT
                      FROM unnest(constraint_record.conkey)
                           WITH ORDINALITY AS key_column(attnum, position)
                      JOIN pg_attribute AS attribute
                        ON attribute.attrelid = constraint_record.conrelid
                       AND attribute.attnum = key_column.attnum
                     ORDER BY key_column.position
               ) = ARRAY['occurred_at', 'correlation_id', 'capability_id', 'model_key', 'tier', 'mode', 'prompt_tokens', 'completion_tokens'];

            IF identity_constraint IS NULL THEN
                RAISE EXCEPTION 'legacy llm_invocation identity constraint is missing';
            END IF;

            EXECUTE format(
                'ALTER TABLE llm_invocation DROP CONSTRAINT %I',
                identity_constraint
            );
        END $$;

        ALTER TABLE llm_invocation
            ADD CONSTRAINT uq_llm_invocation_identity
            UNIQUE (occurred_at, correlation_id, capability_id, model_key, tier, mode, usage_scope, prompt_tokens, completion_tokens);
