-- Migration Revision: core_ontology_property_index_20260830
-- Down Revision: core_ontology_endpoint_integrity_20260830
-- Owner: core-control-plane
-- Extracted SQL Blocks: 2

-- Statement 1
DROP INDEX CONCURRENTLY IF EXISTS idx_ontology_resource_properties_gin;

-- Statement 2
CREATE INDEX CONCURRENTLY idx_ontology_resource_properties_gin ON ontology_resource USING GIN (properties jsonb_path_ops);
