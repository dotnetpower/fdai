-- Migration Revision: executor_safeguard_bundle_read_20260912
-- Down Revision: executor_outbox_pending_index_20260911
-- Owner: isolated-executor
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE INDEX ix_safeguard_dispatch_bundle_digest
        ON safeguard_dispatch_evidence ((record #>> '{bundle,bundle_digest}'));

        REVOKE ALL PRIVILEGES ON TABLE safeguard_dispatch_evidence
        FROM PUBLIC, fdai_executor;
        GRANT SELECT ON TABLE safeguard_dispatch_evidence TO fdai_executor;
