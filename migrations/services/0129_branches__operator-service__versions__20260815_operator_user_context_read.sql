-- Migration Revision: operator_user_context_read_20260815
-- Down Revision: operator_browser_evidence_read_20260815
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE
            user_preference,
            user_memory_fact,
            conversation_policy,
            briefing_subscription,
            briefing_run,
            scheduled_conversation_anchor
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE
            user_preference,
            user_memory_fact,
            conversation_policy,
            briefing_subscription,
            briefing_run,
            scheduled_conversation_anchor
        TO fdai_operator;
