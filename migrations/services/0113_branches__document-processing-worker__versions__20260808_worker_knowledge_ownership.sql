-- Migration Revision: worker_knowledge_ownership_20260808
-- Down Revision: document_worker_effects_20260808
-- Owner: document-processing-worker
-- Extracted SQL Blocks: 4

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE knowledge_chunk FROM fdai_ingestion_api, fdai_ingestion_worker, fdai_ingestion_cohost;

-- Statement 2
GRANT SELECT ON TABLE knowledge_chunk TO fdai_ingestion_api;

-- Statement 3
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE knowledge_chunk TO fdai_ingestion_worker;

-- Statement 4
GRANT SELECT ON TABLE knowledge_chunk TO fdai_ingestion_cohost;
