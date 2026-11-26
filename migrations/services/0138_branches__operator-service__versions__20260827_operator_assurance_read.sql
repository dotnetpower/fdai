-- Migration Revision: operator_assurance_read_20260827
-- Down Revision: operator_runtime_projection_reads_20260827
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE
            conversation_assurance_assessment,
            conversation_assurance_dispute
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE
            conversation_assurance_assessment,
            conversation_assurance_dispute
        TO fdai_operator;
