-- Migration Revision: core_t2_cache_lifecycle_20260831
-- Down Revision: core_cost_governance_settings_20260831
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE
            t2_cache_partition_registry,
            t2_cache_catalog_state,
            t2_cache_catalog_transition,
            t2_cache_rotation_receipt
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT, DELETE
            ON TABLE t2_cache_partition_registry TO fdai_core;
        GRANT SELECT, INSERT, UPDATE
            ON TABLE t2_cache_catalog_state TO fdai_core;
        GRANT SELECT, INSERT
            ON TABLE t2_cache_catalog_transition, t2_cache_rotation_receipt TO fdai_core;
        GRANT EXECUTE
            ON FUNCTION fdai_t2_cache_create_partition(TEXT),
                        fdai_t2_cache_drop_partition(TEXT)
            TO fdai_core;
