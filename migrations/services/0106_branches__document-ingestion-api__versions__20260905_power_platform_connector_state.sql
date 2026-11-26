-- Migration Revision: power_platform_connector_state_20260905
-- Down Revision: sharepoint_delta_state_20260905
-- Owner: document-ingestion-api
-- Extracted SQL Blocks: 10

-- Statement 1
ALTER TABLE document_connector_item ADD COLUMN IF NOT EXISTS source_sequence BIGINT;

-- Statement 2
ALTER TABLE document_connector_item ADD COLUMN IF NOT EXISTS bound_source_revision TEXT;

-- Statement 3
ALTER TABLE document_connector_item ADD COLUMN IF NOT EXISTS content_sha256 TEXT;

-- Statement 4
CREATE TABLE IF NOT EXISTS document_connector_cancellation (
	connector_id TEXT NOT NULL, 
	source_item_id TEXT NOT NULL, 
	source_revision TEXT NOT NULL, 
	status TEXT DEFAULT 'pending' NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (connector_id, source_item_id, source_revision), 
	CONSTRAINT ck_document_connector_cancellation_status CHECK (status IN ('pending', 'completed'))
);

-- Statement 5
REVOKE ALL PRIVILEGES ON TABLE document_connector_cancellation FROM PUBLIC, fdai_ingestion_worker, fdai_ingestion_cohost;

-- Statement 6
GRANT SELECT, INSERT, UPDATE ON TABLE document_connector_cancellation TO fdai_ingestion_api;

-- Statement 7
UPDATE document_connector_item SET bound_source_revision = source_revision WHERE document_id IS NOT NULL;

-- Statement 8
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_document_connector_item_revision_binding') THEN ALTER TABLE document_connector_item ADD CONSTRAINT ck_document_connector_item_revision_binding CHECK ((document_id IS NULL) = (bound_source_revision IS NULL)); END IF; END $$;

-- Statement 9
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_document_connector_item_sequence') THEN ALTER TABLE document_connector_item ADD CONSTRAINT ck_document_connector_item_sequence CHECK (source_sequence IS NULL OR source_sequence >= 0); END IF; END $$;

-- Statement 10
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_document_connector_item_content_sha256') THEN ALTER TABLE document_connector_item ADD CONSTRAINT ck_document_connector_item_content_sha256 CHECK (content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'); END IF; END $$;
