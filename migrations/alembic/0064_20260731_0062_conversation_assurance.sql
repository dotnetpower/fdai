-- Migration Revision: 20260731_0062
-- Down Revision: 20260729_0061
-- Owner: alembic
-- Extracted SQL Blocks: 4

-- Statement 1
CREATE TABLE conversation_assurance_assessment (
            assessment_id TEXT PRIMARY KEY,
            turn_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            principal_scope TEXT NOT NULL,
            question_digest TEXT NOT NULL,
            answer_digest TEXT NOT NULL,
            evidence_manifest_digest TEXT NOT NULL,
            rubric_version TEXT NOT NULL,
            model_set_digest TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('completed', 'deferred', 'disputed')),
            decision JSONB NOT NULL,
            assessed_at TIMESTAMPTZ NOT NULL,
            CHECK (char_length(question_digest) = 64),
            CHECK (char_length(answer_digest) = 64),
            CHECK (char_length(evidence_manifest_digest) = 64)
        );

-- Statement 2
CREATE INDEX idx_conversation_assurance_scope_time ON conversation_assurance_assessment(principal_scope, assessed_at DESC);

-- Statement 3
CREATE TABLE conversation_assurance_dispute (
            dispute_id TEXT PRIMARY KEY,
            assessment_id TEXT NOT NULL REFERENCES conversation_assurance_assessment(assessment_id),
            principal_scope TEXT NOT NULL,
            reported_by TEXT NOT NULL,
            reason TEXT NOT NULL CHECK (
                reason IN (
                    'wrong_fact', 'missing_intent', 'stale_evidence', 'wrong_scope',
                    'inappropriate_abstention', 'language_quality'
                )
            ),
            detail TEXT NOT NULL CHECK (char_length(detail) BETWEEN 1 AND 1000),
            evidence_refs TEXT[] NOT NULL DEFAULT '{}',
            reported_at TIMESTAMPTZ NOT NULL
        );

-- Statement 4
CREATE INDEX idx_conversation_assurance_dispute_scope_time ON conversation_assurance_dispute(principal_scope, reported_at DESC);
