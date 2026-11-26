-- Migration Revision: core_resource_change_receipts_20260912
-- Down Revision: core_recent_resource_changes_20260912
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE inventory_change_event_receipt (
            source_event_id TEXT PRIMARY KEY
                CHECK (char_length(source_event_id) BETWEEN 1 AND 512),
            outcome TEXT NOT NULL
                CHECK (outcome IN ('applied', 'ordering_rejected', 'snapshot_covered')),
            processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        REVOKE ALL PRIVILEGES ON TABLE inventory_change_event_receipt
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT ON TABLE inventory_change_event_receipt TO fdai_core;
