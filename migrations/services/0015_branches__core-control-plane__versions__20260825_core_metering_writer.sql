-- Migration Revision: core_metering_writer_20260825
-- Down Revision: core_operational_archive_20260822
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE llm_invocation FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT ON TABLE llm_invocation TO fdai_core;
