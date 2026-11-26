-- Migration Revision: document_worker_outbox_20260808
-- Down Revision: document_worker_base_20260808
-- Owner: document-processing-worker
-- Extracted SQL Blocks: 5

-- Statement 1
ALTER TABLE document_worker_claim DROP CONSTRAINT IF EXISTS document_worker_claim_stage_check;

-- Statement 2
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'document_worker_claim_stage_check') THEN ALTER TABLE document_worker_claim ADD CONSTRAINT document_worker_claim_stage_check CHECK (stage IN ('received_replay', 'inspection', 'protection_replay', 'safety_decision', 'indexing', 'deletion')); END IF; END $$;

-- Statement 3
CREATE TABLE IF NOT EXISTS document_worker_outbox (
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
REVOKE ALL PRIVILEGES ON TABLE document_worker_outbox FROM PUBLIC, fdai_ingestion_api, fdai_ingestion_cohost;

-- Statement 5
GRANT SELECT, INSERT, UPDATE ON TABLE document_worker_outbox TO fdai_ingestion_worker;
