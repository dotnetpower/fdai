-- Migration Revision: native_sharepoint_connector_state_20260905
-- Down Revision: power_platform_connector_state_20260905
-- Owner: document-ingestion-api
-- Extracted SQL Blocks: 4

-- Statement 1
ALTER TABLE document_connector_item ADD COLUMN IF NOT EXISTS ingestion_outcome TEXT DEFAULT 'pending' NOT NULL;

-- Statement 2
ALTER TABLE document_connector_item ADD COLUMN IF NOT EXISTS failure_code TEXT;

-- Statement 3
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_document_connector_item_ingestion_outcome') THEN ALTER TABLE document_connector_item ADD CONSTRAINT ck_document_connector_item_ingestion_outcome CHECK (ingestion_outcome IN ('pending', 'accepted', 'rejected')); END IF; END $$;

-- Statement 4
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_document_connector_item_failure') THEN ALTER TABLE document_connector_item ADD CONSTRAINT ck_document_connector_item_failure CHECK ((ingestion_outcome = 'rejected') = (failure_code IS NOT NULL)); END IF; END $$;
