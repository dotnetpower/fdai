-- Migration Revision: 20260713_0013
-- Down Revision: 20260713_0012
-- Owner: alembic
-- Extracted SQL Blocks: 16

-- Statement 1
INSERT INTO ontology_object_type (name, version, key_field, properties, description) VALUES ('ReviewCase', '1.0.0', 'id', '{}'::jsonb, 'Current aggregate state of one governed review.') ON CONFLICT (name) DO NOTHING;

-- Statement 2
INSERT INTO ontology_object_type (name, version, key_field, properties, description) VALUES ('ReviewCheck', '1.0.0', 'id', '{}'::jsonb, 'One bounded requirement evaluated during a review.') ON CONFLICT (name) DO NOTHING;

-- Statement 3
INSERT INTO ontology_object_type (name, version, key_field, properties, description) VALUES ('EvidenceArtifact', '1.0.0', 'id', '{}'::jsonb, 'Immutable metadata for externally held evidence.') ON CONFLICT (name) DO NOTHING;

-- Statement 4
INSERT INTO ontology_object_type (name, version, key_field, properties, description) VALUES ('Principal', '1.0.0', 'id', '{}'::jsonb, 'Stable reference to a user, group, service, or agent principal.') ON CONFLICT (name) DO NOTHING;

-- Statement 5
INSERT INTO ontology_object_type (name, version, key_field, properties, description) VALUES ('Approval', '1.0.0', 'id', '{}'::jsonb, 'Action-bound approval request and current decision state.') ON CONFLICT (name) DO NOTHING;

-- Statement 6
INSERT INTO ontology_object_type (name, version, key_field, properties, description) VALUES ('Decision', '1.0.0', 'id', '{}'::jsonb, 'Recorded outcome of a governed review decision point.') ON CONFLICT (name) DO NOTHING;

-- Statement 7
INSERT INTO ontology_link_type (name, version, from_type, to_type, cardinality, description) VALUES ('runs_review', '1.0.0', 'Process', 'ReviewCase', 'one_to_one', 'Review run aggregate.') ON CONFLICT (name) DO NOTHING;

-- Statement 8
INSERT INTO ontology_link_type (name, version, from_type, to_type, cardinality, description) VALUES ('scoped_to', '1.0.0', 'ReviewCase', 'Resource', 'many_to_one', 'Reviewed scope.') ON CONFLICT (name) DO NOTHING;

-- Statement 9
INSERT INTO ontology_link_type (name, version, from_type, to_type, cardinality, description) VALUES ('contains_check', '1.0.0', 'ReviewCase', 'ReviewCheck', 'one_to_many', 'Review check.') ON CONFLICT (name) DO NOTHING;

-- Statement 10
INSERT INTO ontology_link_type (name, version, from_type, to_type, cardinality, description) VALUES ('supported_by', '1.0.0', 'ReviewCheck', 'EvidenceArtifact', 'many_to_many', 'Evidence.') ON CONFLICT (name) DO NOTHING;

-- Statement 11
INSERT INTO ontology_link_type (name, version, from_type, to_type, cardinality, description) VALUES ('assigned_to', '1.0.0', 'ReviewCheck', 'Principal', 'many_to_one', 'Accountable principal.') ON CONFLICT (name) DO NOTHING;

-- Statement 12
INSERT INTO ontology_link_type (name, version, from_type, to_type, cardinality, description) VALUES ('has_approval', '1.0.0', 'ReviewCase', 'Approval', 'one_to_many', 'Approval request.') ON CONFLICT (name) DO NOTHING;

-- Statement 13
INSERT INTO ontology_link_type (name, version, from_type, to_type, cardinality, description) VALUES ('granted_by', '1.0.0', 'Approval', 'Principal', 'many_to_one', 'Approving principal.') ON CONFLICT (name) DO NOTHING;

-- Statement 14
INSERT INTO ontology_link_type (name, version, from_type, to_type, cardinality, description) VALUES ('resolved_by', '1.0.0', 'ReviewCase', 'Decision', 'one_to_many', 'Review decision.') ON CONFLICT (name) DO NOTHING;

-- Statement 15
INSERT INTO ontology_link_type (name, version, from_type, to_type, cardinality, description) VALUES ('based_on', '1.0.0', 'Decision', 'EvidenceArtifact', 'many_to_many', 'Decision evidence.') ON CONFLICT (name) DO NOTHING;

-- Statement 16
INSERT INTO ontology_link_type (name, version, from_type, to_type, cardinality, description) VALUES ('produces_finding', '1.0.0', 'ReviewCheck', 'Finding', 'one_to_many', 'Failed check finding.') ON CONFLICT (name) DO NOTHING;
