-- Migration Revision: core_inventory_activity_counts_20260917
-- Down Revision: core_inventory_temporal_axes_20260916
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
ALTER TABLE inventory_snapshot
            ADD COLUMN resource_count BIGINT,
            ADD COLUMN link_count BIGINT;

        ALTER TABLE inventory_snapshot
            ADD CONSTRAINT ck_inventory_snapshot_resource_count_nonnegative
                CHECK (resource_count IS NULL OR resource_count >= 0),
            ADD CONSTRAINT ck_inventory_snapshot_link_count_nonnegative
                CHECK (link_count IS NULL OR link_count >= 0);

        WITH counts AS (
            SELECT snapshot_id, COUNT(*) AS value
              FROM inventory_snapshot_resource
             GROUP BY snapshot_id
        )
        UPDATE inventory_snapshot AS snapshot
           SET resource_count = counts.value
          FROM counts
         WHERE snapshot.id = counts.snapshot_id
           AND snapshot.status IN ('active', 'superseded');

        UPDATE inventory_snapshot
           SET resource_count = 0
         WHERE status IN ('active', 'superseded')
           AND resource_count IS NULL;

        WITH counts AS (
            SELECT snapshot_id, COUNT(*) AS value
              FROM inventory_snapshot_link
             GROUP BY snapshot_id
        )
        UPDATE inventory_snapshot AS snapshot
           SET link_count = counts.value
          FROM counts
         WHERE snapshot.id = counts.snapshot_id
           AND snapshot.status IN ('active', 'superseded');

        UPDATE inventory_snapshot
           SET link_count = 0
         WHERE status IN ('active', 'superseded')
           AND link_count IS NULL;
