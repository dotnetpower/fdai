-- Migration Revision: 20260801_0067
-- Down Revision: 20260731_0066
-- Owner: alembic
-- Extracted SQL Blocks: 6

-- Statement 1
ALTER TABLE ontology_resource ADD COLUMN type_version TEXT, ADD COLUMN catalog_digest TEXT;

-- Statement 2
ALTER TABLE ontology_link ADD COLUMN type_version TEXT, ADD COLUMN catalog_digest TEXT;

-- Statement 3
ALTER TABLE ontology_resource ADD CONSTRAINT ontology_resource_type_version_format CHECK (type_version IS NULL OR type_version ~ '^[0-9]+\.[0-9]+\.[0-9]+$'), ADD CONSTRAINT ontology_resource_catalog_digest_format CHECK (catalog_digest IS NULL OR catalog_digest ~ '^sha256:[a-f0-9]{64}$');

-- Statement 4
ALTER TABLE ontology_link ADD CONSTRAINT ontology_link_type_version_format CHECK (type_version IS NULL OR type_version ~ '^[0-9]+\.[0-9]+\.[0-9]+$'), ADD CONSTRAINT ontology_link_catalog_digest_format CHECK (catalog_digest IS NULL OR catalog_digest ~ '^sha256:[a-f0-9]{64}$');

-- Statement 5
ALTER TABLE ontology_resource ADD CONSTRAINT ontology_resource_type_ref_pair CHECK ((type_version IS NULL) = (catalog_digest IS NULL));

-- Statement 6
ALTER TABLE ontology_link ADD CONSTRAINT ontology_link_type_ref_pair CHECK ((type_version IS NULL) = (catalog_digest IS NULL));
