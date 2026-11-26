-- Migration Revision: core_inventory_temporal_axes_20260916
-- Down Revision: core_alert_forecast_merge_20260915
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
ALTER TABLE inventory_observation_journal
            ADD COLUMN provider_event_at TIMESTAMPTZ,
            ADD COLUMN ingested_at TIMESTAMPTZ;

        ALTER TABLE inventory_observation_journal
            DISABLE TRIGGER inventory_observation_journal_no_modify;

        UPDATE inventory_observation_journal
        SET ingested_at = recorded_at
        WHERE ingested_at IS NULL;

        ALTER TABLE inventory_observation_journal
            ENABLE TRIGGER inventory_observation_journal_no_modify;

        ALTER TABLE inventory_observation_journal
            ALTER COLUMN ingested_at SET NOT NULL;
