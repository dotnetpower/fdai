-- Migration Revision: operator_workflow_definition_read_20260929
-- Down Revision: operator_rule_activation_receipts_20260922
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE workflow_definition, workflow_binding
            FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE workflow_definition, workflow_binding TO fdai_operator;
