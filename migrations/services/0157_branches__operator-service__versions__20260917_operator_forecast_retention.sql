-- Migration Revision: operator_forecast_retention_20260917
-- Down Revision: operator_inventory_progress_read_20260916
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE VIEW operator_forecast_retention
        WITH (security_barrier = true) AS
        SELECT COUNT(*) FILTER (
                   WHERE deletion_started_at IS NOT NULL AND deleted_at IS NULL
               ) AS pending,
               COUNT(*) FILTER (
                   WHERE deleted_at IS NULL AND deletion_due_at < now()
               ) AS overdue
          FROM case_history;
        REVOKE ALL PRIVILEGES ON TABLE operator_forecast_retention FROM PUBLIC;
        GRANT SELECT ON TABLE operator_forecast_retention TO fdai_operator;
