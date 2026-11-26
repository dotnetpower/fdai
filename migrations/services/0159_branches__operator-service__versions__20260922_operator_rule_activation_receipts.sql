-- Migration Revision: operator_rule_activation_receipts_20260922
-- Down Revision: operator_chaos_report_read_20260921
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL ON TABLE operator_rule_activation_receipt FROM fdai_operator;
