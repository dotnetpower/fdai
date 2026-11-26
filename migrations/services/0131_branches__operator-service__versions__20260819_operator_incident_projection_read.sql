-- Migration Revision: operator_incident_projection_read_20260819
-- Down Revision: operator_user_context_read_20260815
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE operator_incident_projection
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE operator_incident_projection TO fdai_operator;
