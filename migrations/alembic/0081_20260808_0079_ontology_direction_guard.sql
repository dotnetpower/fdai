-- Migration Revision: 20260808_0079
-- Down Revision: 20260808_0078
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
DELETE FROM ontology_link
        WHERE link_type = 'contains'
          AND (type_version = '1.0.0' OR type_version IS NULL);

        UPDATE ontology_resource
        SET type_version = NULL, catalog_digest = NULL
        WHERE catalog_digest = 'sha256:dd90ae7025bb0472cc091c23e8ed763f7d2ff94a109daf0295a60bb732f33037';

        UPDATE ontology_link
        SET type_version = NULL, catalog_digest = NULL
        WHERE catalog_digest = 'sha256:dd90ae7025bb0472cc091c23e8ed763f7d2ff94a109daf0295a60bb732f33037';

        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'ontology_link'::regclass
                  AND conname = 'ontology_link_contains_version_direction'
            ) THEN
                ALTER TABLE ontology_link
                ADD CONSTRAINT ontology_link_contains_version_direction
                CHECK (
                    link_type <> 'contains'
                    OR (type_version IS NOT NULL AND type_version <> '1.0.0')
                );
            END IF;
        END
        $$;
