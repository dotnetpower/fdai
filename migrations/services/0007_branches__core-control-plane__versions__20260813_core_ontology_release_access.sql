-- Migration Revision: core_ontology_release_access_20260813
-- Down Revision: core_inventory_routes_links_20260810
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE ontology_release TO fdai_core;
