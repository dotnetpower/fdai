-- Migration Revision: operator_conversation_search_read_20260814
-- Down Revision: operator_activity_read_20260812
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE
            conversation_record,
            conversation_turn
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE
            conversation_record,
            conversation_turn
        TO fdai_operator;
