-- Migration Revision: operator_conversation_policy_evidence_20260907
-- Down Revision: operator_inventory_invalidation_read_20260906
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
ALTER TABLE conversation_assurance_policy_transition
            ADD COLUMN decision_evidence_receipt_digest TEXT,
            ADD COLUMN decision_evidence_verification_bundle_digest TEXT,
            ADD CONSTRAINT ck_assurance_policy_transition_decision_evidence_pair
                CHECK (
                    (decision_evidence_receipt_digest IS NULL)
                    = (decision_evidence_verification_bundle_digest IS NULL)
                ),
            ADD CONSTRAINT ck_assurance_policy_transition_receipt_digest
                CHECK (
                    decision_evidence_receipt_digest IS NULL
                    OR decision_evidence_receipt_digest ~ '^sha256:[a-f0-9]{64}$'
                ),
            ADD CONSTRAINT ck_assurance_policy_transition_bundle_digest
                CHECK (
                    decision_evidence_verification_bundle_digest IS NULL
                    OR decision_evidence_verification_bundle_digest
                        ~ '^sha256:[a-f0-9]{64}$'
                );
