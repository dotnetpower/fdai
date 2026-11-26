-- Migration Revision: core_metering_sequence_20260825
-- Down Revision: core_incident_recovery_index_20260825
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON SEQUENCE llm_invocation_invocation_id_seq
            FROM PUBLIC, fdai_core;
        GRANT USAGE, SELECT ON SEQUENCE llm_invocation_invocation_id_seq TO fdai_core;
