-- Migration Revision: core_operational_evidence_action_history_20261003
-- Down Revision: core_workflow_catalog_writer_20261002
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE FUNCTION fdai_forecast_action_history_audit(
            p_target_ref TEXT,
            p_start_at TIMESTAMPTZ,
            p_end_at TIMESTAMPTZ,
            p_limit INTEGER
        ) RETURNS TABLE (
            seq BIGINT,
            recorded_at TIMESTAMPTZ,
            entry JSONB,
            previous_hash TEXT,
            entry_hash TEXT,
            state_value JSONB
        ) LANGUAGE SQL STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp AS $$
            SELECT audit.seq::BIGINT,
                   audit.created_at AS recorded_at,
                   CASE WHEN run.value ->> 'resource_id' = p_target_ref
                        THEN audit.entry ELSE NULL::JSONB END AS entry,
                   audit.previous_hash::TEXT,
                   audit.entry_hash::TEXT,
                   CASE WHEN run.value ->> 'resource_id' = p_target_ref
                        THEN run.value ELSE NULL::JSONB END AS state_value
              FROM public.audit_log AS audit
              LEFT JOIN public.state_kv AS run
                ON run.key = 'thor:run|' || (audit.entry ->> 'correlation_id')
             WHERE char_length(p_target_ref) BETWEEN 1 AND 512
               AND p_start_at IS NOT NULL
               AND p_end_at IS NOT NULL
               AND p_start_at <= p_end_at
               AND p_limit BETWEEN 1 AND 512
               AND audit.action_kind = 'thor.action-run-save'
               AND audit.created_at >= p_start_at
               AND audit.created_at <= p_end_at
             ORDER BY audit.seq
             LIMIT p_limit
        $$;
        REVOKE ALL ON FUNCTION fdai_forecast_action_history_audit(
            TEXT, TIMESTAMPTZ, TIMESTAMPTZ, INTEGER
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION fdai_forecast_action_history_audit(
            TEXT, TIMESTAMPTZ, TIMESTAMPTZ, INTEGER
        ) TO fdai_operational_evidence_verifier;
