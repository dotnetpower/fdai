-- Migration Revision: operator_assignment_receipts_20260914
-- Down Revision: operator_conversation_document_refs_20260914
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
GRANT SELECT, INSERT ON TABLE operator_assignment_receipt TO fdai_operator;
