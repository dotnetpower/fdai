-- Migration Revision: 20260705_0003
-- Down Revision: 20260705_0002
-- Owner: alembic
-- Extracted SQL Blocks: 10

-- Statement 1
INSERT INTO ontology_object_type
                (name, version, key_field, properties, description)
            VALUES ('Resource', '1.0.0', 'resource_id', '{}'::jsonb, 'A cloud resource under governance; populated by the Inventory adapter.')
            ON CONFLICT (name) DO NOTHING;

-- Statement 2
INSERT INTO ontology_object_type
                (name, version, key_field, properties, description)
            VALUES ('Rule', '1.0.0', 'id', '{}'::jsonb, 'A deterministic control with an intent (applies_to, evaluates, remediates).')
            ON CONFLICT (name) DO NOTHING;

-- Statement 3
INSERT INTO ontology_object_type
                (name, version, key_field, properties, description)
            VALUES ('Signal', '1.0.0', 'signal_id', '{}'::jsonb, 'A typed observation (Activity Log line, drift diff, cost anomaly, canary result).')
            ON CONFLICT (name) DO NOTHING;

-- Statement 4
INSERT INTO ontology_object_type
                (name, version, key_field, properties, description)
            VALUES ('Finding', '1.0.0', 'finding_id', '{}'::jsonb, 'A rule match on a resource at a point in time; audited.')
            ON CONFLICT (name) DO NOTHING;

-- Statement 5
INSERT INTO ontology_link_type
                (name, version, from_type, to_type, cardinality, description)
            VALUES ('contains', '1.0.0', 'Resource', 'Resource', 'many_to_one', 'Ownership / scope containment: subscription→resource-group→resource, VNet→subnet, cluster→node-pool. Recursive.')
            ON CONFLICT (name) DO NOTHING;

-- Statement 6
INSERT INTO ontology_link_type
                (name, version, from_type, to_type, cardinality, description)
            VALUES ('attached_to', '1.0.0', 'Resource', 'Resource', 'many_to_one', 'Lifetime-bound attachment: NIC→VM, disk→VM, private-endpoint→target.')
            ON CONFLICT (name) DO NOTHING;

-- Statement 7
INSERT INTO ontology_link_type
                (name, version, from_type, to_type, cardinality, description)
            VALUES ('depends_on', '1.0.0', 'Resource', 'Resource', 'many_to_many', 'Logical reference required for correct operation: ContainerApp→Key-Vault, managed-identity→app. Broken edges degrade the dependent.')
            ON CONFLICT (name) DO NOTHING;

-- Statement 8
INSERT INTO ontology_link_type
                (name, version, from_type, to_type, cardinality, description)
            VALUES ('resource_of', '1.0.0', 'Signal', 'Resource', 'many_to_one', 'Which resource a signal is about.')
            ON CONFLICT (name) DO NOTHING;

-- Statement 9
INSERT INTO ontology_link_type
                (name, version, from_type, to_type, cardinality, description)
            VALUES ('precedes', '1.0.0', 'Finding', 'Finding', 'many_to_many', 'Temporal ordering of correlated findings on one incident.')
            ON CONFLICT (name) DO NOTHING;

-- Statement 10
INSERT INTO ontology_link_type
                (name, version, from_type, to_type, cardinality, description)
            VALUES ('follows', '1.0.0', 'Finding', 'Finding', 'many_to_many', 'Reverse of `precedes`; kept explicit for query symmetry.')
            ON CONFLICT (name) DO NOTHING;
