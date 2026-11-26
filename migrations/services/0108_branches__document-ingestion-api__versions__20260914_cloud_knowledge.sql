-- Migration Revision: cloud_knowledge_20260914
-- Down Revision: document_lifecycle_convergence_20260905
-- Owner: document-ingestion-api
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE document_knowledge_source (
            registry_digest TEXT NOT NULL, source_id TEXT NOT NULL,
            revision BIGINT NOT NULL DEFAULT 0 CHECK (revision >= 0),
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            claim_id UUID, lease_until TIMESTAMPTZ,
            PRIMARY KEY (registry_digest, source_id)
        );
        CREATE TABLE document_knowledge_check (
            digest TEXT PRIMARY KEY, registry_digest TEXT NOT NULL, source_id TEXT NOT NULL,
            payload JSONB NOT NULL, recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
        );
        CREATE TABLE document_knowledge_release (
            collection_id TEXT NOT NULL, sequence BIGINT NOT NULL CHECK (sequence > 0),
            manifest_digest TEXT NOT NULL, upload_id UUID NOT NULL, payload JSONB NOT NULL,
            imported_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (collection_id, sequence), UNIQUE (manifest_digest)
        );
        REVOKE ALL ON document_knowledge_source, document_knowledge_check,
            document_knowledge_release FROM PUBLIC;
        DO $grant$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fdai_ingestion_api') THEN
                GRANT SELECT, INSERT, UPDATE ON document_knowledge_source TO fdai_ingestion_api;
                GRANT SELECT, INSERT ON document_knowledge_check, document_knowledge_release
                    TO fdai_ingestion_api;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fdai_core') THEN
                GRANT SELECT ON document_knowledge_source TO fdai_core;
            END IF;
        END $grant$;
