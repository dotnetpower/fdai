-- Migration Revision: core_current_case_reuse_source_20261003
-- Down Revision: core_operational_evidence_action_history_20261003
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE FUNCTION fdai_current_case_reuse_source(p_key TEXT)
        RETURNS JSONB LANGUAGE SQL STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp AS $$
            SELECT state.value
              FROM public.state_kv AS state
             WHERE starts_with(p_key, 'current-case-reuse:v1:')
               AND state.key = p_key
        $$;
        REVOKE ALL ON FUNCTION fdai_current_case_reuse_source(TEXT) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION fdai_current_case_reuse_source(TEXT)
        TO fdai_operational_evidence_verifier;
