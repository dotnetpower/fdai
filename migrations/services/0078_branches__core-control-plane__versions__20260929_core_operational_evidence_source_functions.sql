-- Migration Revision: core_operational_evidence_source_functions_20260929
-- Down Revision: core_operational_evidence_20260928
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE FUNCTION fdai_operational_evidence_commands_for_key(p_idempotency_key TEXT)
        RETURNS TABLE (
            key TEXT, record JSONB, dispatch_status TEXT, authentication_receipt JSONB
        ) LANGUAGE SQL STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp AS $$
            SELECT command.key, command.record, command.dispatch_status,
                   command.authentication_receipt
              FROM public.operational_evidence_test_context_command AS command
             WHERE char_length(p_idempotency_key) BETWEEN 1 AND 256
               AND command.record ->> 'idempotency_key' = p_idempotency_key
             ORDER BY command.key
             LIMIT 2
        $$;
        CREATE FUNCTION fdai_operational_evidence_commands_for_target(
            p_access_scope_digest TEXT, p_target_ref TEXT
        ) RETURNS TABLE (
            key TEXT, record JSONB, dispatch_status TEXT, authentication_receipt JSONB
        ) LANGUAGE SQL STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp AS $$
            SELECT command.key, command.record, command.dispatch_status,
                   command.authentication_receipt
              FROM public.operational_evidence_test_context_command AS command
             WHERE command.access_scope_digest = p_access_scope_digest
               AND command.target_ref = p_target_ref
             ORDER BY command.key
             LIMIT 65
        $$;
        CREATE FUNCTION fdai_operational_evidence_context_history(p_key TEXT)
        RETURNS JSONB LANGUAGE SQL STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp AS $$
            SELECT history.value
              FROM public.operational_evidence_test_context_history AS history
             WHERE starts_with(p_key, 'test-context-target:v1:')
               AND history.key = p_key
        $$;
        CREATE FUNCTION fdai_operational_evidence_transition_audit(p_context_digests TEXT[])
        RETURNS TABLE (
            seq BIGINT, entry JSONB, previous_hash TEXT, entry_hash TEXT
        ) LANGUAGE SQL STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp AS $$
            SELECT audit.seq::BIGINT, audit.entry, audit.previous_hash::TEXT,
                   audit.entry_hash::TEXT
              FROM public.operational_evidence_test_context_audit AS audit
             WHERE cardinality(p_context_digests) BETWEEN 1 AND 256
               AND audit.entry ->> 'context_digest' = ANY (p_context_digests)
             ORDER BY audit.seq
             LIMIT 257
        $$;
        REVOKE ALL ON FUNCTION
            fdai_operational_evidence_commands_for_key(TEXT),
            fdai_operational_evidence_commands_for_target(TEXT, TEXT),
            fdai_operational_evidence_context_history(TEXT),
            fdai_operational_evidence_transition_audit(TEXT[])
        FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION
            fdai_operational_evidence_commands_for_key(TEXT),
            fdai_operational_evidence_commands_for_target(TEXT, TEXT),
            fdai_operational_evidence_context_history(TEXT),
            fdai_operational_evidence_transition_audit(TEXT[])
        TO fdai_operational_evidence_verifier;
        REVOKE ALL ON TABLE
            operational_evidence_test_context_command,
            operational_evidence_test_context_history,
            operational_evidence_test_context_audit
        FROM fdai_operational_evidence_verifier;
