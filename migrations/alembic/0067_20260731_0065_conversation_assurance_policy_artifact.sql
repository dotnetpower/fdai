-- Migration Revision: 20260731_0065
-- Down Revision: 20260731_0064
-- Owner: alembic
-- Extracted SQL Blocks: 2

-- Statement 1
ALTER TABLE conversation_assurance_policy_candidate ADD COLUMN policy_text TEXT;

-- Statement 2
ALTER TABLE conversation_assurance_policy_candidate ADD CONSTRAINT ck_assurance_policy_candidate_text CHECK (policy_text IS NULL OR char_length(policy_text) BETWEEN 1 AND 2000);
