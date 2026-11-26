-- Migration Revision: 20260817_0085
-- Down Revision: 20260814_0084
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'ontology_release') THEN
        PERFORM 1 FROM ontology_release WHERE digest = 'sha256:596873529ea6b479363fa34b07c326db02117726ac4d790f42a9abc707c6939d';
    END IF;
END $$;
