-- Migration Revision: core_inventory_progress_retention_20260921
-- Down Revision: core_canonical_incident_storage_20260921
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE FUNCTION fdai_prune_inventory_progress(retain_terminal_attempts INTEGER)
        RETURNS BIGINT
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $function$
        DECLARE
            deleted_rows BIGINT;
        BEGIN
            IF retain_terminal_attempts < 1 OR retain_terminal_attempts > 1000 THEN
                RAISE EXCEPTION 'inventory progress terminal retention is outside its bound'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM pg_advisory_xact_lock(
                hashtextextended('inventory-progress-retention', 0)
            );

            WITH latest_attempt_state AS MATERIALIZED (
                SELECT DISTINCT ON (run_id, attempt_id)
                       run_id,
                       attempt_id,
                       event_id,
                                             state,
                       NULLIF(
                           payload->>'deadline_at',
                           ''
                       )::TIMESTAMPTZ AS deadline_at
                  FROM inventory_progress_event
                 ORDER BY run_id, attempt_id, sequence DESC, event_id DESC
            ),
                        expired_terminal_attempts AS MATERIALIZED (
                SELECT run_id, attempt_id
                  FROM latest_attempt_state
                 WHERE state IN ('complete', 'failed')
                 ORDER BY event_id DESC, run_id DESC, attempt_id DESC
                OFFSET retain_terminal_attempts
                        ),
                        expired_attempts AS MATERIALIZED (
                                SELECT run_id, attempt_id
                                    FROM expired_terminal_attempts
                                UNION ALL
                                SELECT run_id, attempt_id
                                    FROM latest_attempt_state
                                 WHERE state = 'running'
                                     AND deadline_at < CURRENT_TIMESTAMP
            )
            DELETE FROM inventory_progress_event AS progress
             USING expired_attempts AS expired
             WHERE progress.run_id = expired.run_id
               AND progress.attempt_id = expired.attempt_id;

            GET DIAGNOSTICS deleted_rows = ROW_COUNT;
            RETURN deleted_rows;
        END;
        $function$;

        REVOKE ALL PRIVILEGES ON FUNCTION fdai_prune_inventory_progress(INTEGER)
        FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION fdai_prune_inventory_progress(INTEGER) TO fdai_core;
