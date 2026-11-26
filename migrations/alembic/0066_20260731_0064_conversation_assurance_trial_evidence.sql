-- Migration Revision: 20260731_0064
-- Down Revision: 20260731_0063
-- Owner: alembic
-- Extracted SQL Blocks: 5

-- Statement 1
ALTER TABLE conversation_assurance_policy_transition ADD COLUMN evidence_digest TEXT;

-- Statement 2
UPDATE conversation_assurance_policy_transition SET evidence_digest = transition_key WHERE evidence_digest IS NULL;

-- Statement 3
ALTER TABLE conversation_assurance_policy_transition ALTER COLUMN evidence_digest SET NOT NULL;

-- Statement 4
ALTER TABLE conversation_assurance_policy_transition ADD CONSTRAINT ck_assurance_policy_transition_evidence_digest CHECK (char_length(evidence_digest) = 64);

-- Statement 5
CREATE UNIQUE INDEX uq_assurance_policy_transition_candidate_evidence ON conversation_assurance_policy_transition(candidate_id, evidence_digest);
