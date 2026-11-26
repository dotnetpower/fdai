-- Migration Revision: 20260709_0001
-- Down Revision: 20260708_0008
-- Owner: alembic
-- Extracted SQL Blocks: 3

-- Statement 1
INSERT INTO ontology_object_type
                (name, version, key_field, properties, description)
            VALUES ('Process', '1.0.0', 'id', '{}'::jsonb, 'Runtime instance and state of one Workflow run over a target Resource.')
            ON CONFLICT (name) DO NOTHING;

-- Statement 2
INSERT INTO ontology_link_type
                (name, version, from_type, to_type, cardinality, description)
            VALUES ('targets', '1.0.0', 'Process', 'Resource', 'many_to_one', 'The primary Resource a Process operates on.')
            ON CONFLICT (name) DO NOTHING;

-- Statement 3
INSERT INTO ontology_link_type
                (name, version, from_type, to_type, cardinality, description)
            VALUES ('advances', '1.0.0', 'Process', 'Finding', 'many_to_many', 'The ordered Findings a Process advanced through during its run.')
            ON CONFLICT (name) DO NOTHING;
