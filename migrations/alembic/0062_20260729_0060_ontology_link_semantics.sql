-- Migration Revision: 20260729_0060
-- Down Revision: 20260725_0059
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
ALTER TABLE ontology_link_type ADD COLUMN IF NOT EXISTS is_transitive BOOLEAN NOT NULL DEFAULT FALSE, ADD COLUMN IF NOT EXISTS is_causal BOOLEAN NOT NULL DEFAULT FALSE, ADD COLUMN IF NOT EXISTS temporal_order BOOLEAN NOT NULL DEFAULT FALSE, ADD COLUMN IF NOT EXISTS order_by_property TEXT;
