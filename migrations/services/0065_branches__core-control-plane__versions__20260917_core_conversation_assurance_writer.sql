-- Migration Revision: core_conversation_assurance_writer_20260917
-- Down Revision: core_cost_governance_live_20260917
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE
            conversation_assurance_assessment,
            conversation_assurance_dispute
        FROM fdai_core;
        GRANT SELECT, INSERT ON TABLE
            conversation_assurance_assessment,
            conversation_assurance_dispute
        TO fdai_core;
