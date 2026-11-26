-- Migration Revision: document_intent_envelope_20261020
-- Down Revision: cloud_knowledge_lexical_20260914
-- Owner: document-processing-worker
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE document_intent_envelope (
            document_id UUID NOT NULL,
            version_id UUID NOT NULL,
            envelope JSONB NOT NULL,
            envelope_digest TEXT NOT NULL CHECK(envelope_digest ~ '^sha256:[0-9a-f]{64}$'),
            source_sha256 TEXT NOT NULL CHECK(source_sha256 ~ '^[0-9a-f]{64}$'),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY(document_id, version_id)
        );
        REVOKE ALL ON document_intent_envelope FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON document_intent_envelope TO fdai_ingestion_worker;
        CREATE FUNCTION fdai_document_intent_envelope(p_document UUID, p_version UUID)
        RETURNS JSONB LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path=pg_catalog,public AS $$
          SELECT envelope FROM public.document_intent_envelope
          WHERE document_id=p_document AND version_id=p_version
        $$;
        REVOKE ALL ON FUNCTION fdai_document_intent_envelope(UUID,UUID) FROM PUBLIC;
