-- Migration Revision: operator_handover_document_read_20260905
-- Down Revision: operator_cost_governance_settings_read_20260831
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE document_version FROM PUBLIC, fdai_operator;
        CREATE OR REPLACE FUNCTION fdai_verify_handover_document(
            p_principal_id TEXT,
            p_document_id UUID,
            p_version_id UUID,
            p_source_sha256 TEXT
        )
        RETURNS BOOLEAN
        LANGUAGE SQL
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT EXISTS (
                SELECT 1
                  FROM public.document_version AS version
                 WHERE version.document_id = p_document_id
                   AND version.version_id = p_version_id
                   AND version.state IN ('ready', 'ready_with_warnings')
                   AND version.active
                   AND version.payload ->> 'uploader_id' = p_principal_id
                   AND version.payload ->> 'source_sha256' = p_source_sha256
                   AND (version.payload ->> 'available')::BOOLEAN
            )
        $$;
        REVOKE ALL ON FUNCTION fdai_verify_handover_document(
            TEXT, UUID, UUID, TEXT
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION fdai_verify_handover_document(
            TEXT, UUID, UUID, TEXT
        ) TO fdai_operator;
