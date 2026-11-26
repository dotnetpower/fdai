-- Migration Revision: core_code_security_automation_20261010
-- Down Revision: core_code_security_role_20261009
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE OR REPLACE FUNCTION fdai_code_security_key_allowed(p_key TEXT) RETURNS BOOLEAN
        LANGUAGE SQL IMMUTABLE SET search_path = pg_catalog AS $$
            SELECT COALESCE(length(p_key) BETWEEN 1 AND 512 AND
                p_key ~ '^runtime:code-security-(repository|review|issues|schedule|revision|worker):.+$', FALSE)
        $$;

        CREATE OR REPLACE FUNCTION fdai_code_security_states(p_prefix TEXT, p_limit INTEGER)
        RETURNS TABLE(value JSONB) LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public AS $$
        BEGIN
            IF p_prefix NOT IN ('runtime:code-security-repository:', 'runtime:code-security-review:', 'runtime:code-security-issues:', 'runtime:code-security-schedule:', 'runtime:code-security-revision:', 'runtime:code-security-worker:')
                OR p_prefix IS NULL OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 1000 THEN
                RAISE EXCEPTION 'code-security state list scope denied' USING ERRCODE = '42501';
            END IF;
            RETURN QUERY SELECT state.value FROM public.state_kv AS state
                WHERE starts_with(state.key, p_prefix)
                ORDER BY state.updated_at DESC, state.key LIMIT p_limit;
        END $$;
