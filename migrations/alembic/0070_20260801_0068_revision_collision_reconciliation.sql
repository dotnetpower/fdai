-- Migration Revision: 20260801_0068
-- Down Revision: 20260801_0067
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
ALTER TABLE ontology_resource
            ADD COLUMN IF NOT EXISTS type_version TEXT,
            ADD COLUMN IF NOT EXISTS catalog_digest TEXT;

        ALTER TABLE ontology_link
            ADD COLUMN IF NOT EXISTS type_version TEXT,
            ADD COLUMN IF NOT EXISTS catalog_digest TEXT;

        ALTER TABLE case_history
            ALTER COLUMN detector_id DROP NOT NULL,
            ALTER COLUMN detector_version DROP NOT NULL,
            ALTER COLUMN metric DROP NOT NULL,
            ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

        ALTER TABLE case_history_revision
            ALTER COLUMN detector_id DROP NOT NULL,
            ALTER COLUMN detector_version DROP NOT NULL,
            ALTER COLUMN metric DROP NOT NULL,
            ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'ontology_resource'::regclass
                  AND conname = 'ontology_resource_type_version_format'
            ) THEN
                ALTER TABLE ontology_resource
                    ADD CONSTRAINT ontology_resource_type_version_format
                    CHECK (type_version IS NULL OR type_version ~ '^[0-9]+\.[0-9]+\.[0-9]+$');
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'ontology_resource'::regclass
                  AND conname = 'ontology_resource_catalog_digest_format'
            ) THEN
                ALTER TABLE ontology_resource
                    ADD CONSTRAINT ontology_resource_catalog_digest_format
                    CHECK (catalog_digest IS NULL OR catalog_digest ~ '^sha256:[a-f0-9]{64}$');
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'ontology_resource'::regclass
                  AND conname = 'ontology_resource_type_ref_pair'
            ) THEN
                ALTER TABLE ontology_resource
                    ADD CONSTRAINT ontology_resource_type_ref_pair
                    CHECK ((type_version IS NULL) = (catalog_digest IS NULL));
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'ontology_link'::regclass
                  AND conname = 'ontology_link_type_version_format'
            ) THEN
                ALTER TABLE ontology_link
                    ADD CONSTRAINT ontology_link_type_version_format
                    CHECK (type_version IS NULL OR type_version ~ '^[0-9]+\.[0-9]+\.[0-9]+$');
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'ontology_link'::regclass
                  AND conname = 'ontology_link_catalog_digest_format'
            ) THEN
                ALTER TABLE ontology_link
                    ADD CONSTRAINT ontology_link_catalog_digest_format
                    CHECK (catalog_digest IS NULL OR catalog_digest ~ '^sha256:[a-f0-9]{64}$');
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'ontology_link'::regclass
                  AND conname = 'ontology_link_type_ref_pair'
            ) THEN
                ALTER TABLE ontology_link
                    ADD CONSTRAINT ontology_link_type_ref_pair
                    CHECK ((type_version IS NULL) = (catalog_digest IS NULL));
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'case_history'::regclass
                  AND conname = 'ck_case_history_kind_metadata'
            ) THEN
                ALTER TABLE case_history
                    ADD CONSTRAINT ck_case_history_kind_metadata CHECK (
                        (kind = 'prediction'
                            AND detector_id IS NOT NULL
                            AND detector_version IS NOT NULL
                            AND metric IS NOT NULL)
                        OR (kind IN ('action', 'incident')
                            AND detector_id IS NULL
                            AND detector_version IS NULL
                            AND metric IS NULL)
                    );
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'case_history'::regclass
                  AND conname = 'ck_case_history_metadata_object'
            ) THEN
                ALTER TABLE case_history
                    ADD CONSTRAINT ck_case_history_metadata_object
                    CHECK (jsonb_typeof(metadata) = 'object');
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'case_history_revision'::regclass
                  AND conname = 'ck_case_history_revision_forecast_metadata'
            ) THEN
                ALTER TABLE case_history_revision
                    ADD CONSTRAINT ck_case_history_revision_forecast_metadata CHECK (
                        (detector_id IS NOT NULL
                            AND detector_version IS NOT NULL
                            AND metric IS NOT NULL)
                        OR (detector_id IS NULL
                            AND detector_version IS NULL
                            AND metric IS NULL)
                    );
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'case_history_revision'::regclass
                  AND conname = 'ck_case_history_revision_metadata_object'
            ) THEN
                ALTER TABLE case_history_revision
                    ADD CONSTRAINT ck_case_history_revision_metadata_object
                    CHECK (jsonb_typeof(metadata) = 'object');
            END IF;
        END
        $$;
