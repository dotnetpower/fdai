-- Migration Revision: sharepoint_delta_state_20260905
-- Down Revision: ingestion_api_outbox_20260808
-- Owner: document-ingestion-api
-- Extracted SQL Blocks: 10

-- Statement 1
CREATE TABLE IF NOT EXISTS document_connector_cursor (
	connector_id TEXT NOT NULL, 
	revision BIGINT NOT NULL, 
	payload JSON NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (connector_id)
);

-- Statement 2
CREATE TABLE IF NOT EXISTS document_connector_batch (
	idempotency_key TEXT NOT NULL, 
	connector_id TEXT NOT NULL, 
	collection_id TEXT NOT NULL, 
	access_descriptor_ref TEXT NOT NULL, 
	applied_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (idempotency_key)
);

-- Statement 3
CREATE TABLE IF NOT EXISTS document_connector_item (
	connector_id TEXT NOT NULL, 
	source_item_id TEXT NOT NULL, 
	source_revision TEXT NOT NULL, 
	source_name TEXT, 
	size_bytes BIGINT NOT NULL, 
	deleted BOOLEAN NOT NULL, 
	collection_id TEXT NOT NULL, 
	access_descriptor_ref TEXT NOT NULL, 
	document_id UUID, 
	version_id UUID, 
	deletion_pending BOOLEAN DEFAULT false NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (connector_id, source_item_id), 
	FOREIGN KEY(document_id, version_id) REFERENCES document_version (document_id, version_id), 
	CONSTRAINT ck_document_connector_item_version_binding CHECK ((document_id IS NULL) = (version_id IS NULL)), 
	CONSTRAINT ck_document_connector_item_size CHECK (size_bytes >= 0)
);

-- Statement 4
REVOKE ALL PRIVILEGES ON TABLE document_connector_cursor FROM PUBLIC, fdai_ingestion_worker, fdai_ingestion_cohost;

-- Statement 5
REVOKE ALL PRIVILEGES ON TABLE document_connector_batch FROM PUBLIC, fdai_ingestion_worker, fdai_ingestion_cohost;

-- Statement 6
REVOKE ALL PRIVILEGES ON TABLE document_connector_item FROM PUBLIC, fdai_ingestion_worker, fdai_ingestion_cohost;

-- Statement 7
GRANT SELECT, INSERT, UPDATE ON TABLE document_connector_cursor TO fdai_ingestion_api;

-- Statement 8
GRANT SELECT, INSERT, UPDATE ON TABLE document_connector_batch TO fdai_ingestion_api;

-- Statement 9
GRANT SELECT, INSERT, UPDATE ON TABLE document_connector_item TO fdai_ingestion_api;

-- Statement 10
CREATE OR REPLACE FUNCTION enforce_document_lifecycle_transition_owner()
        RETURNS TRIGGER LANGUAGE plpgsql AS $lifecycle$
        DECLARE api_allowed BOOLEAN; worker_allowed BOOLEAN;
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
                OR (OLD.state NOT IN ('deleting', 'deleted') AND NEW.state = 'deleting');
            worker_allowed :=
                (OLD.state = 'received' AND NEW.state = 'quarantined')
                OR (OLD.state = 'quarantined' AND NEW.state = 'scanning')
                OR (OLD.state = 'scanning' AND NEW.state = 'protection_check')
                OR (OLD.state = 'protection_check' AND NEW.state IN ('extracting', 'ready', 'held'))
                OR (OLD.state = 'extracting' AND NEW.state IN ('indexing', 'failed'))
                OR (
                    OLD.state = 'indexing'
                    AND NEW.state IN ('ready', 'ready_with_warnings', 'failed')
                )
                OR (OLD.state = 'deleting' AND NEW.state = 'deleted')
                OR (
                    TG_TABLE_NAME = 'document_version' AND OLD.state = NEW.state
                    AND (
                        (
                            to_jsonb(OLD)->>'active' = 'true'
                            AND to_jsonb(NEW)->>'active' = 'false'
                        )
                        OR (
                            OLD.payload->>'available' = 'true'
                            AND NEW.payload->>'available' = 'false'
                            AND NEW.payload->>'protection_state' = 'rights_managed_access_denied'
                        )
                    )
                );
            IF current_user = 'fdai_ingestion_api' AND NOT api_allowed THEN
                RAISE EXCEPTION 'fdai_ingestion_api does not own this lifecycle transition';
            ELSIF current_user = 'fdai_ingestion_worker' AND NOT worker_allowed THEN
                RAISE EXCEPTION 'fdai_ingestion_worker does not own this lifecycle transition';
            ELSIF current_user = 'fdai_ingestion_cohost'
                  AND NOT (api_allowed OR worker_allowed) THEN
                RAISE EXCEPTION 'fdai_ingestion_cohost does not own this lifecycle transition';
            END IF;
            RETURN NEW;
        END;
        $lifecycle$;
