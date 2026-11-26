-- Migration Revision: operator_skill_proposal_evidence_20260912
-- Down Revision: operator_conversation_policy_evidence_20260907
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
ALTER TABLE skill_proposal
        ADD COLUMN IF NOT EXISTS evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(evidence_refs) = 'array');
