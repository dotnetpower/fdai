-- Migration Revision: cloud_knowledge_lexical_20260914
-- Down Revision: document_protection_reconciliation_20260905
-- Owner: document-processing-worker
-- Extracted SQL Blocks: 3

-- Statement 1
ALTER TABLE knowledge_chunk ALTER COLUMN embedding DROP NOT NULL;

-- Statement 2
ALTER TABLE document_worker_effect DROP CONSTRAINT ck_document_worker_effect_kind;

-- Statement 3
ALTER TABLE document_worker_effect ADD CONSTRAINT ck_document_worker_effect_kind CHECK (effect_kind IN ('source_promotion', 'ephemeral_source_cleanup', 'deletion_cleanup', 'knowledge_activation'));
