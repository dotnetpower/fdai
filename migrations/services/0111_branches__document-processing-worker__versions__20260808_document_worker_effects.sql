-- Migration Revision: document_worker_effects_20260808
-- Down Revision: document_worker_outbox_20260808
-- Owner: document-processing-worker
-- Extracted SQL Blocks: 4

-- Statement 1
CREATE TABLE IF NOT EXISTS document_worker_effect (
	effect_id UUID NOT NULL, 
	upload_id UUID NOT NULL, 
	document_id UUID NOT NULL, 
	version_id UUID NOT NULL, 
	effect_kind TEXT NOT NULL, 
	object_key TEXT NOT NULL, 
	status TEXT DEFAULT 'pending' NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	attempt_count INTEGER DEFAULT '0' NOT NULL, 
	next_attempt_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (effect_id), 
	FOREIGN KEY(upload_id) REFERENCES document_upload_session (upload_id) ON DELETE CASCADE, 
	CONSTRAINT uq_document_worker_effect_kind UNIQUE (upload_id, effect_kind), 
	CONSTRAINT ck_document_worker_effect_kind CHECK (effect_kind IN ('source_promotion', 'ephemeral_source_cleanup', 'deletion_cleanup')), 
	CONSTRAINT ck_document_worker_effect_status CHECK (status IN ('pending', 'completed')), 
	CONSTRAINT ck_document_worker_effect_completion CHECK ((status = 'pending' AND completed_at IS NULL) OR (status = 'completed' AND completed_at IS NOT NULL))
);

-- Statement 2
CREATE INDEX IF NOT EXISTS ix_document_worker_effect_pending ON document_worker_effect (next_attempt_at, created_at, effect_id);

-- Statement 3
REVOKE ALL PRIVILEGES ON TABLE document_worker_effect FROM PUBLIC, fdai_ingestion_api, fdai_ingestion_cohost;

-- Statement 4
GRANT SELECT, INSERT, UPDATE ON TABLE document_worker_effect TO fdai_ingestion_worker;
