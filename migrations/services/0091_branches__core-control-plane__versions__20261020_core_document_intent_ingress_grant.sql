-- Migration Revision: core_document_intent_ingress_20261020
-- Down Revision: core_document_intent_20261019
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
GRANT EXECUTE ON FUNCTION fdai_document_intent_envelope(UUID,UUID) TO fdai_core;
