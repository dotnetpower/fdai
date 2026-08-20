"""Grant Core runtime access to append-only question assurance ledgers."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_question_assurance_20260820"
down_revision: str | Sequence[str] | None = "core_question_campaign_20260819"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "question_campaign_novelty",
    "question_failure_review",
    "question_failure_review_decision",
    "question_manual_campaign_review",
    "question_release_assurance",
    "question_review_projection",
)
rollback = {
    "strategy": "drop-question-assurance-ledgers",
    "restores": "core_question_campaign_20260819",
    "requires": "core-runtime-stopped",
}


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE question_campaign_novelty (
            campaign_id TEXT NOT NULL REFERENCES question_campaign(campaign_id),
            case_id TEXT NOT NULL CHECK (char_length(case_id) BETWEEN 1 AND 256),
            generation_attempt INTEGER NOT NULL CHECK (generation_attempt BETWEEN 1 AND 10),
            question_fingerprint TEXT NOT NULL
                CHECK (question_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
            exact_duplicate BOOLEAN NOT NULL,
            semantic_duplicate BOOLEAN NOT NULL,
            semantic_duplicate_threshold DOUBLE PRECISION NOT NULL
                CHECK (semantic_duplicate_threshold BETWEEN 0 AND 1),
            accepted BOOLEAN NOT NULL,
            record JSONB NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (campaign_id, case_id, generation_attempt),
            CHECK (accepted <> (exact_duplicate OR semantic_duplicate)),
            CHECK (jsonb_typeof(record) = 'object')
        );
        CREATE UNIQUE INDEX uq_question_campaign_novelty_accepted_fingerprint
            ON question_campaign_novelty(question_fingerprint) WHERE accepted;
        CREATE INDEX idx_question_campaign_novelty_release_locale
            ON question_campaign_novelty (
                (record->>'ontology_release_digest'),
                (record->>'locale'),
                (record->>'perspective')
            );

        CREATE TABLE question_review_projection (
            record_id TEXT PRIMARY KEY CHECK (char_length(record_id) BETWEEN 1 AND 256),
            campaign_id TEXT NOT NULL REFERENCES question_campaign(campaign_id),
            case_id TEXT NOT NULL CHECK (char_length(case_id) BETWEEN 1 AND 256),
            question_digest TEXT NOT NULL CHECK (question_digest ~ '^sha256:[0-9a-f]{64}$'),
            answer_digest TEXT NOT NULL CHECK (answer_digest ~ '^sha256:[0-9a-f]{64}$'),
            adequacy_receipt_digest TEXT NOT NULL
                CHECK (adequacy_receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
            record JSONB NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL,
            delete_after TIMESTAMPTZ NOT NULL,
            CHECK (delete_after > recorded_at),
            CHECK (jsonb_typeof(record) = 'object'),
            CHECK (NOT (record ? 'question')),
            CHECK (NOT (record ? 'answer')),
            CHECK (NOT (record ? 'rationales')),
            CHECK (
                record - ARRAY[
                    'record_id',
                    'campaign_id',
                    'case_id',
                    'question_digest',
                    'answer_digest',
                    'rationale_digests',
                    'criterion_scores',
                    'adequacy_verdict',
                    'adequacy_receipt_digest',
                    'retention_policy_digest',
                    'recorded_at',
                    'delete_after'
                ]::TEXT[] = '{}'::jsonb
            ),
            CHECK (jsonb_typeof(record->'rationale_digests') = 'array'),
            CHECK (jsonb_array_length(record->'rationale_digests') <= 32)
        );
        CREATE INDEX idx_question_review_projection_expiry
            ON question_review_projection(delete_after);

        CREATE TABLE question_failure_review (
            review_id TEXT PRIMARY KEY CHECK (char_length(review_id) BETWEEN 1 AND 256),
            campaign_id TEXT NOT NULL REFERENCES question_campaign(campaign_id),
            case_id TEXT NOT NULL CHECK (char_length(case_id) BETWEEN 1 AND 256),
            semantic_pair_id TEXT NOT NULL CHECK (char_length(semantic_pair_id) BETWEEN 1 AND 256),
            ontology_release_digest TEXT NOT NULL
                CHECK (ontology_release_digest ~ '^sha256:[0-9a-f]{64}$'),
            question_digest TEXT NOT NULL CHECK (question_digest ~ '^sha256:[0-9a-f]{64}$'),
            answer_digest TEXT NOT NULL CHECK (answer_digest ~ '^sha256:[0-9a-f]{64}$'),
            adequacy_receipt_digest TEXT NOT NULL
                CHECK (adequacy_receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
            record JSONB NOT NULL,
            submitted_at TIMESTAMPTZ NOT NULL,
            CHECK (jsonb_typeof(record) = 'object')
        );

        CREATE TABLE question_failure_review_decision (
            review_id TEXT PRIMARY KEY REFERENCES question_failure_review(review_id),
            decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
            human_principal_digest TEXT NOT NULL
                CHECK (human_principal_digest ~ '^sha256:[0-9a-f]{64}$'),
            human_authorization_receipt_digest TEXT NOT NULL
                CHECK (human_authorization_receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
            authorization_expires_at TIMESTAMPTZ NOT NULL,
            reason_code TEXT NOT NULL CHECK (char_length(reason_code) BETWEEN 1 AND 256),
            target_corpus_version TEXT NULL,
            record JSONB NOT NULL,
            decided_at TIMESTAMPTZ NOT NULL,
            CHECK ((decision = 'approved') = (target_corpus_version IS NOT NULL)),
            CHECK (authorization_expires_at > decided_at),
            CHECK (jsonb_typeof(record) = 'object')
        );

        CREATE TABLE question_manual_campaign_review (
            campaign_id TEXT PRIMARY KEY REFERENCES question_campaign(campaign_id),
            ontology_release_digest TEXT NOT NULL
                CHECK (ontology_release_digest ~ '^sha256:[0-9a-f]{64}$'),
            novelty_rate DOUBLE PRECISION NOT NULL CHECK (novelty_rate BETWEEN 0 AND 1),
            new_failure_count INTEGER NOT NULL CHECK (new_failure_count >= 0),
            coverage_delta_count INTEGER NOT NULL CHECK (coverage_delta_count >= 0),
            human_principal_digest TEXT NOT NULL
                CHECK (human_principal_digest ~ '^sha256:[0-9a-f]{64}$'),
            human_review_receipt_digest TEXT NOT NULL
                CHECK (human_review_receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
            record JSONB NOT NULL,
            reviewed_at TIMESTAMPTZ NOT NULL,
            CHECK (jsonb_typeof(record) = 'object'),
            CHECK (record->>'mode' = 'shadow')
        );
        CREATE INDEX idx_question_manual_review_release_time
            ON question_manual_campaign_review(ontology_release_digest, reviewed_at);

        CREATE TABLE question_release_assurance (
            receipt_digest TEXT PRIMARY KEY
                CHECK (receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
            source_revision TEXT NOT NULL CHECK (source_revision ~ '^[0-9a-f]{40}$'),
            ontology_release_digest TEXT NOT NULL
                CHECK (ontology_release_digest ~ '^sha256:[0-9a-f]{64}$'),
            golden_corpus_digest TEXT NOT NULL
                CHECK (golden_corpus_digest ~ '^sha256:[0-9a-f]{64}$'),
            generated_campaign_id TEXT NULL REFERENCES question_campaign(campaign_id),
            passed BOOLEAN NOT NULL,
            record JSONB NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (NOT passed OR generated_campaign_id IS NOT NULL),
            CHECK (jsonb_typeof(record) = 'object'),
            CHECK (record->'execution_authority' = 'false'::jsonb)
        );
        CREATE INDEX idx_question_release_assurance_campaign_passed
            ON question_release_assurance(generated_campaign_id, passed);
        CREATE INDEX idx_question_release_assurance_release_time
            ON question_release_assurance(ontology_release_digest, recorded_at);
        """
    )
    op.execute("GRANT SELECT, INSERT ON TABLE question_campaign_novelty TO fdai_core")
    op.execute("GRANT SELECT, INSERT ON TABLE question_failure_review TO fdai_core")
    op.execute("GRANT SELECT, INSERT ON TABLE question_failure_review_decision TO fdai_core")
    op.execute("GRANT SELECT, INSERT ON TABLE question_manual_campaign_review TO fdai_core")
    op.execute("GRANT SELECT, INSERT ON TABLE question_release_assurance TO fdai_core")
    op.execute("GRANT SELECT, INSERT ON TABLE question_review_projection TO fdai_core")


def downgrade() -> None:
    op.execute("REVOKE SELECT, INSERT ON TABLE question_review_projection FROM fdai_core")
    op.execute("REVOKE SELECT, INSERT ON TABLE question_release_assurance FROM fdai_core")
    op.execute("REVOKE SELECT, INSERT ON TABLE question_manual_campaign_review FROM fdai_core")
    op.execute("REVOKE SELECT, INSERT ON TABLE question_failure_review_decision FROM fdai_core")
    op.execute("REVOKE SELECT, INSERT ON TABLE question_failure_review FROM fdai_core")
    op.execute("REVOKE SELECT, INSERT ON TABLE question_campaign_novelty FROM fdai_core")
    op.execute("DROP TABLE question_release_assurance")
    op.execute("DROP TABLE question_manual_campaign_review")
    op.execute("DROP TABLE question_failure_review_decision")
    op.execute("DROP TABLE question_failure_review")
    op.execute("DROP TABLE question_review_projection")
    op.execute("DROP TABLE question_campaign_novelty")
