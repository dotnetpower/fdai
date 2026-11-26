-- Migration Revision: 20260806_0076
-- Down Revision: 20260806_0075
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fdai_ingestion_api') THEN
                CREATE ROLE fdai_ingestion_api NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fdai_ingestion_worker') THEN
                CREATE ROLE fdai_ingestion_worker NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fdai_ingestion_cohost') THEN
                CREATE ROLE fdai_ingestion_cohost NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
            END IF;
        END
        $$;

        GRANT fdai_ingestion_api, fdai_ingestion_worker, fdai_ingestion_cohost TO CURRENT_USER;
        GRANT USAGE ON SCHEMA public
            TO fdai_ingestion_api, fdai_ingestion_worker, fdai_ingestion_cohost;

        GRANT SELECT, INSERT, UPDATE
            ON document_upload_session, document_version
            TO fdai_ingestion_api;
        GRANT SELECT, INSERT, UPDATE, DELETE ON state_kv TO fdai_ingestion_api;
        GRANT SELECT, INSERT ON audit_log TO fdai_ingestion_api;
        GRANT SELECT, DELETE ON knowledge_chunk TO fdai_ingestion_api;

        GRANT SELECT, UPDATE
            ON document_upload_session, document_version
            TO fdai_ingestion_worker;
        GRANT SELECT, INSERT, UPDATE, DELETE
            ON document_worker_claim, knowledge_chunk, state_kv
            TO fdai_ingestion_worker;
        GRANT SELECT, INSERT ON audit_log TO fdai_ingestion_worker;

        GRANT SELECT, INSERT, UPDATE, DELETE
            ON document_upload_session, document_version, document_worker_claim,
               knowledge_chunk, state_kv
            TO fdai_ingestion_cohost;
        GRANT SELECT, INSERT ON audit_log TO fdai_ingestion_cohost;

        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public
            TO fdai_ingestion_api, fdai_ingestion_worker, fdai_ingestion_cohost;
