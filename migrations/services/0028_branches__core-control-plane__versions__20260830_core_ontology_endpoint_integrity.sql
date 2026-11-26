-- Migration Revision: core_ontology_endpoint_integrity_20260830
-- Down Revision: core_catalog_lifecycle_20260829
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                  FROM ontology_link AS link
                  LEFT JOIN ontology_resource AS source
                    ON source.id = link.from_id
                  LEFT JOIN ontology_resource AS target
                    ON target.id = link.to_id
                 WHERE source.id IS NULL OR target.id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'cannot enforce ontology endpoint integrity while dangling links exist';
            END IF;
        END
        $$;

        ALTER TABLE ontology_link
            ADD CONSTRAINT ontology_link_from_resource_fk
            FOREIGN KEY (from_id) REFERENCES ontology_resource(id)
            ON DELETE CASCADE NOT VALID;
        ALTER TABLE ontology_link
            ADD CONSTRAINT ontology_link_to_resource_fk
            FOREIGN KEY (to_id) REFERENCES ontology_resource(id)
            ON DELETE CASCADE NOT VALID;
        ALTER TABLE ontology_link
            VALIDATE CONSTRAINT ontology_link_from_resource_fk;
        ALTER TABLE ontology_link
            VALIDATE CONSTRAINT ontology_link_to_resource_fk;
