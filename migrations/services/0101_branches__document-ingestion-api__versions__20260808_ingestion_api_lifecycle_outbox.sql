-- Migration Revision: ingestion_api_outbox_20260808
-- Down Revision: ingestion_api_base_20260808
-- Owner: document-ingestion-api
-- Extracted SQL Blocks: 6

-- Statement 1
ALTER TABLE document_upload_session ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL;

-- Statement 2
ALTER TABLE document_version ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL;

-- Statement 3
CREATE TABLE document_api_outbox (
	event_id UUID NOT NULL, 
	idempotency_key TEXT NOT NULL, 
	topic TEXT NOT NULL, 
	partition_key TEXT NOT NULL, 
	payload JSON NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	published_at TIMESTAMP WITH TIME ZONE, 
	attempt_count INTEGER DEFAULT '0' NOT NULL, 
	next_attempt_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (event_id), 
	UNIQUE (idempotency_key)
);

-- Statement 4
REVOKE ALL PRIVILEGES ON TABLE document_api_outbox FROM PUBLIC, fdai_ingestion_worker, fdai_ingestion_cohost;

-- Statement 5
GRANT SELECT, INSERT, UPDATE ON TABLE document_api_outbox TO fdai_ingestion_api;

-- Statement 6
CREATE FUNCTION enforce_document_lifecycle_transition_owner()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $lifecycle$
        DECLARE
            api_allowed BOOLEAN;
            worker_allowed BOOLEAN;
        BEGIN
            IF NEW.revision <> OLD.revision + 1 THEN
                RAISE EXCEPTION 'document lifecycle revision must increment exactly once';
            END IF;
            IF NEW.payload->>'state' IS DISTINCT FROM NEW.state
               OR (NEW.payload->>'revision')::BIGINT IS DISTINCT FROM NEW.revision THEN
                RAISE EXCEPTION
                    'document lifecycle payload must match relational state and revision';
            END IF;

            api_allowed :=
                (OLD.state = 'created' AND NEW.state = 'uploading')
                OR (OLD.state = 'uploading' AND NEW.state IN ('received', 'held'))
                OR (
                    OLD.state NOT IN ('deleting', 'deleted')
                    AND NEW.state = 'deleting'
                );
            worker_allowed :=
                (OLD.state = 'received' AND NEW.state = 'quarantined')
                OR (OLD.state = 'quarantined' AND NEW.state = 'scanning')
                OR (OLD.state = 'scanning' AND NEW.state = 'protection_check')
                OR (
                    OLD.state = 'protection_check'
                    AND NEW.state IN ('extracting', 'ready', 'held')
                )
                OR (OLD.state = 'extracting' AND NEW.state IN ('indexing', 'failed'))
                OR (
                    OLD.state = 'indexing'
                    AND NEW.state IN ('ready', 'ready_with_warnings', 'failed')
                )
                OR (OLD.state = 'deleting' AND NEW.state = 'deleted')
                OR (
                    TG_TABLE_NAME = 'document_version'
                    AND OLD.state = NEW.state
                    AND to_jsonb(OLD)->>'active' = 'true'
                    AND to_jsonb(NEW)->>'active' = 'false'
                );

            IF current_user = 'fdai_ingestion_api' AND NOT api_allowed THEN
                RAISE EXCEPTION
                    'fdai_ingestion_api does not own this lifecycle transition';
            ELSIF current_user = 'fdai_ingestion_worker' AND NOT worker_allowed THEN
                RAISE EXCEPTION
                    'fdai_ingestion_worker does not own this lifecycle transition';
            ELSIF current_user = 'fdai_ingestion_cohost'
                  AND NOT (api_allowed OR worker_allowed) THEN
                RAISE EXCEPTION
                    'fdai_ingestion_cohost does not own this lifecycle transition';
            END IF;
            RETURN NEW;
        END;
        $lifecycle$;

        CREATE TRIGGER document_upload_session_transition_owner
        BEFORE UPDATE ON document_upload_session
        FOR EACH ROW EXECUTE FUNCTION enforce_document_lifecycle_transition_owner();

        CREATE TRIGGER document_version_transition_owner
        BEFORE UPDATE ON document_version
        FOR EACH ROW EXECUTE FUNCTION enforce_document_lifecycle_transition_owner();
