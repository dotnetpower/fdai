-- Migration Revision: 20260720_0038
-- Down Revision: 20260720_0037
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE EXTENSION IF NOT EXISTS pg_trgm;

        ALTER TABLE conversation_turn
            ADD COLUMN search_text TEXT
            GENERATED ALWAYS AS (lower(content)) STORED;

        CREATE INDEX ix_conversation_turn_search_scope
            ON conversation_turn (principal_id, recorded_at DESC, conversation_id);
        CREATE INDEX ix_conversation_turn_search_trgm
            ON conversation_turn USING GIN (search_text gin_trgm_ops);
        CREATE INDEX ix_conversation_turn_search_incident
            ON conversation_turn (principal_id, (metadata ->> 'incident_id'))
            WHERE metadata ? 'incident_id';
        CREATE INDEX ix_conversation_turn_search_correlation
            ON conversation_turn (principal_id, (metadata ->> 'correlation_id'))
            WHERE metadata ? 'correlation_id';
