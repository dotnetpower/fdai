-- Migration Revision: 20260813_0081
-- Down Revision: 20260813_0080
-- Owner: alembic
-- Extracted SQL Blocks: 2

-- Statement 1
CREATE TABLE ontology_release (
            digest TEXT PRIMARY KEY,
            manifest JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_ontology_release_digest
                CHECK (digest ~ '^sha256:[0-9a-f]{64}$'),
            CONSTRAINT ck_ontology_release_manifest_object
                CHECK (jsonb_typeof(manifest) = 'object'),
            CONSTRAINT ck_ontology_release_manifest_digest
                CHECK (manifest ->> 'digest' = digest),
            CONSTRAINT ck_ontology_release_declarations_array
                CHECK (jsonb_typeof(manifest -> 'declarations') = 'array')
        );

-- Statement 2
INSERT INTO ontology_release (digest, manifest) VALUES ('sha256:596873529ea6b479363fa34b07c326db02117726ac4d790f42a9abc707c6939d', '{"schema_version":"1.0.0","declarations":[]}'::jsonb) ON CONFLICT (digest) DO NOTHING;
