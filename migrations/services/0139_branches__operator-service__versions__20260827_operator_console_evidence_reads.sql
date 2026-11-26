-- Migration Revision: operator_console_evidence_reads_20260827
-- Down Revision: operator_assurance_read_20260827
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE
            forecast_episode,
            forecast_publication_outbox,
            operator_memory,
            memory_compaction_candidate,
            skill_source,
            skill_source_refresh_state
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE
            forecast_episode,
            forecast_publication_outbox,
            operator_memory,
            memory_compaction_candidate,
            skill_source,
            skill_source_refresh_state
        TO fdai_operator;
