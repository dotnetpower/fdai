-- Migration Revision: 20260808_0078
-- Down Revision: 20260806_0077
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
DELETE FROM ontology_link
                WHERE link_type = 'contains'
                    AND (type_version = '1.0.0' OR type_version IS NULL);

        DELETE FROM ontology_link AS link
        USING ontology_resource AS source
        WHERE link.link_type = 'attached_to'
          AND link.from_id = source.id
          AND source.object_type = 'Resource'
          AND source.properties ->> 'type' = 'compute.vm';

                UPDATE ontology_resource
                SET type_version = NULL, catalog_digest = NULL
                WHERE catalog_digest = 'sha256:dd90ae7025bb0472cc091c23e8ed763f7d2ff94a109daf0295a60bb732f33037';

                UPDATE ontology_link
                SET type_version = NULL, catalog_digest = NULL
                WHERE catalog_digest = 'sha256:dd90ae7025bb0472cc091c23e8ed763f7d2ff94a109daf0295a60bb732f33037';

        UPDATE ontology_link_type
        SET version = '2.0.0',
            cardinality = 'one_to_many',
            description = 'Ownership / scope containment from parent to child; '
                || 'recursive traversal walks descendants.'
        WHERE name = 'contains';

        ALTER TABLE ontology_link
        ADD CONSTRAINT ontology_link_contains_version_direction
        CHECK (
            link_type <> 'contains'
            OR (type_version IS NOT NULL AND type_version <> '1.0.0')
        );
