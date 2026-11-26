-- Migration Revision: core_shared_data_ownership_20260808
-- Down Revision: core_base_20260808
-- Owner: core-control-plane
-- Extracted SQL Blocks: 7

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE state_kv FROM fdai_ingestion_api, fdai_ingestion_worker, fdai_ingestion_cohost;

-- Statement 2
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE state_kv TO fdai_ingestion_api, fdai_ingestion_worker;

-- Statement 3
GRANT SELECT ON TABLE state_kv TO fdai_ingestion_cohost;

-- Statement 4
REVOKE INSERT, UPDATE, DELETE ON TABLE audit_log FROM fdai_ingestion_api, fdai_ingestion_worker, fdai_ingestion_cohost;

-- Statement 5
REVOKE TRUNCATE, REFERENCES, TRIGGER ON TABLE audit_log FROM fdai_ingestion_api, fdai_ingestion_worker, fdai_ingestion_cohost;

-- Statement 6
GRANT SELECT ON TABLE audit_log TO fdai_ingestion_api, fdai_ingestion_worker, fdai_ingestion_cohost;

-- Statement 7
CREATE OR REPLACE FUNCTION enforce_state_kv_namespace_owner()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $state_owner$
        DECLARE
            source_key TEXT;
            target_key TEXT;
        BEGIN
            source_key := CASE WHEN TG_OP = 'INSERT' THEN NEW.key ELSE OLD.key END;
            target_key := CASE WHEN TG_OP = 'DELETE' THEN OLD.key ELSE NEW.key END;
            IF current_user = 'fdai_ingestion_api'
               AND NOT (
                   (
                       starts_with(source_key, 'stewardship_merge:')
                       OR starts_with(source_key, 'stewardship_repository_draft:')
                   )
                   AND (
                       starts_with(target_key, 'stewardship_merge:')
                       OR starts_with(target_key, 'stewardship_repository_draft:')
                   )
               ) THEN
                RAISE EXCEPTION
                    'fdai_ingestion_api does not own this state_kv namespace';
            ELSIF current_user = 'fdai_ingestion_worker'
                  AND NOT (
                      starts_with(source_key, 'handover_draft:')
                      AND starts_with(target_key, 'handover_draft:')
                  ) THEN
                RAISE EXCEPTION
                    'fdai_ingestion_worker does not own this state_kv namespace';
            ELSIF current_user = 'fdai_ingestion_cohost' THEN
                RAISE EXCEPTION
                    'fdai_ingestion_cohost has no state_kv write ownership';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $state_owner$;

        CREATE TRIGGER state_kv_namespace_owner
        BEFORE INSERT OR DELETE OR UPDATE ON state_kv
        FOR EACH ROW EXECUTE FUNCTION enforce_state_kv_namespace_owner();
