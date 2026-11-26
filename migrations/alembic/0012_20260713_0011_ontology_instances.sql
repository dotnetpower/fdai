-- Migration Revision: 20260713_0011
-- Down Revision: 20260712_0010
-- Owner: alembic
-- Extracted SQL Blocks: 2

-- Statement 1
ALTER TABLE ontology_resource ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 1 CHECK (revision >= 1);

-- Statement 2
CREATE UNIQUE INDEX IF NOT EXISTS uq_ontology_link_identity ON ontology_link(from_id, link_type, to_id);
