-- Migration Revision: native_sharepoint_resync_state_20260905
-- Down Revision: native_sharepoint_connector_state_20260905
-- Owner: document-ingestion-api
-- Extracted SQL Blocks: 2

-- Statement 1
ALTER TABLE document_connector_item ADD COLUMN IF NOT EXISTS sync_epoch BIGINT DEFAULT 0 NOT NULL;

-- Statement 2
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_document_connector_item_sync_epoch') THEN ALTER TABLE document_connector_item ADD CONSTRAINT ck_document_connector_item_sync_epoch CHECK (sync_epoch >= 0); END IF; END $$;
