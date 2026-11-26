-- Migration Revision: core_workflow_catalog_writer_20261002
-- Down Revision: core_operational_evidence_forecast_sources_20261002
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
GRANT SELECT, INSERT, UPDATE ON TABLE workflow_definition TO fdai_core;
