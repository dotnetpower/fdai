-- Migration Revision: document_protection_reconciliation_20260905
-- Down Revision: worker_knowledge_ownership_20260808
-- Owner: document-processing-worker
-- Extracted SQL Blocks: 4

-- Statement 1
CREATE TABLE IF NOT EXISTS document_protection_reconciliation (
	document_id UUID NOT NULL, 
	version_id UUID NOT NULL, 
	upload_id UUID NOT NULL, 
	source_sha256 VARCHAR(64) NOT NULL, 
	provider_ref TEXT NOT NULL, 
	policy_revision BIGINT NOT NULL, 
	protection_state TEXT NOT NULL, 
	status TEXT DEFAULT 'active' NOT NULL, 
	next_check_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	claim_owner TEXT, 
	lease_expires_at TIMESTAMP WITH TIME ZONE, 
	revision BIGINT DEFAULT '1' NOT NULL, 
	last_checked_at TIMESTAMP WITH TIME ZONE, 
	reason_code TEXT, 
	PRIMARY KEY (document_id, version_id), 
	FOREIGN KEY(document_id, version_id) REFERENCES document_version (document_id, version_id) ON DELETE CASCADE, 
	FOREIGN KEY(upload_id) REFERENCES document_upload_session (upload_id) ON DELETE CASCADE, 
	CONSTRAINT ck_document_protection_reconciliation_status CHECK (status IN ('active', 'cleanup_pending', 'revoked')), 
	CONSTRAINT ck_document_protection_reconciliation_digest CHECK (char_length(source_sha256) = 64), 
	CONSTRAINT ck_document_protection_reconciliation_lease CHECK ((claim_owner IS NULL) = (lease_expires_at IS NULL))
);

-- Statement 2
CREATE INDEX IF NOT EXISTS ix_document_protection_reconciliation_due ON document_protection_reconciliation (status, next_check_at, document_id, version_id);

-- Statement 3
REVOKE ALL PRIVILEGES ON TABLE document_protection_reconciliation FROM PUBLIC, fdai_ingestion_api, fdai_ingestion_cohost;

-- Statement 4
GRANT SELECT, INSERT, UPDATE ON TABLE document_protection_reconciliation TO fdai_ingestion_worker;
