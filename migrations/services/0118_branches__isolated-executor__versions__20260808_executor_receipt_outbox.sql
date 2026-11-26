-- Migration Revision: executor_receipt_outbox_20260808
-- Down Revision: executor_base_20260808
-- Owner: isolated-executor
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE executor_receipt_outbox (
	receipt_id UUID NOT NULL, 
	partition_key TEXT NOT NULL, 
	payload JSON NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	published_at TIMESTAMP WITH TIME ZONE, 
	attempt_count INTEGER DEFAULT '0' NOT NULL, 
	next_attempt_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (receipt_id)
);
