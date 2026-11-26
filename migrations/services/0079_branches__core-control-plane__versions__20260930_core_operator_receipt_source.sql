-- Migration Revision: core_operator_receipt_source_20260930
-- Down Revision: core_licensing_trial_20260929
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
SET LOCAL check_function_bodies = off;
        CREATE FUNCTION fdai_operator_authentication_receipt_for_request(
            p_receipt_digest TEXT,
            p_request_id TEXT
        )
        RETURNS TABLE (
            receipt_digest TEXT,
            request_id TEXT,
            principal_id TEXT,
            receipt JSONB,
            recorded_at TIMESTAMPTZ
        ) LANGUAGE SQL STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp AS $$
            SELECT source.receipt_digest, source.request_id, source.principal_id,
                   source.receipt, source.recorded_at
              FROM public.operator_authentication_receipt AS source
             WHERE p_receipt_digest ~ '^sha256:[0-9a-f]{64}$'
               AND char_length(p_request_id) BETWEEN 1 AND 256
               AND source.receipt_digest = p_receipt_digest
               AND source.request_id = p_request_id
             ORDER BY source.recorded_at DESC
             LIMIT 2
        $$;
        REVOKE ALL ON FUNCTION fdai_operator_authentication_receipt_for_request(TEXT, TEXT)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION fdai_operator_authentication_receipt_for_request(TEXT, TEXT)
            TO fdai_operational_evidence_verifier;
