-- Migration Revision: 20260717_0033
-- Down Revision: 20260717_0032
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
ALTER TABLE user_preference
            ADD COLUMN answer_detail TEXT NOT NULL DEFAULT 'standard'
                CHECK (answer_detail IN ('brief', 'standard', 'deep')),
            ADD COLUMN answer_format TEXT NOT NULL DEFAULT 'prose'
                CHECK (answer_format IN (
                    'prose', 'bullets', 'numbered_steps', 'table', 'checklist', 'mixed'
                )),
            ADD COLUMN answer_preferences_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN answer_intent_detail JSONB NOT NULL DEFAULT '{}'::jsonb
                CHECK (jsonb_typeof(answer_intent_detail) = 'object'),
            ADD COLUMN answer_intent_format JSONB NOT NULL DEFAULT '{}'::jsonb
                CHECK (jsonb_typeof(answer_intent_format) = 'object');
