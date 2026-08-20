"""Create append-only question campaign ledgers and grant Core runtime access."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_question_campaign_20260819"
down_revision: str | Sequence[str] | None = "core_incident_projection_20260819"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "question_campaign",
    "question_campaign_attempt",
    "question_campaign_case_claim",
    "question_campaign_completion",
)
rollback = {
    "strategy": "retain-question-campaign-schema-revoke-runtime-access",
    "restores": "core_incident_projection_20260819",
    "requires": "core-runtime-stopped",
}


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS question_campaign (
            campaign_id TEXT PRIMARY KEY CHECK (campaign_id ~ '^qs:[0-9a-f]{64}$'),
            source_revision TEXT NOT NULL CHECK (source_revision ~ '^[0-9a-f]{40}$'),
            ontology_release_digest TEXT NOT NULL
                CHECK (ontology_release_digest ~ '^sha256:[0-9a-f]{64}$'),
            question_universe_digest TEXT NOT NULL
                CHECK (question_universe_digest ~ '^sha256:[0-9a-f]{64}$'),
            started_at TIMESTAMPTZ NOT NULL,
            trigger_kind TEXT NOT NULL
                CHECK (trigger_kind IN ('manual', 'scheduled', 'release_certification')),
            identity JSONB NOT NULL,
            CHECK (jsonb_typeof(identity) = 'object')
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_question_campaign_source_started "
        "ON question_campaign(source_revision, started_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_question_campaign_universe_started "
        "ON question_campaign(question_universe_digest, started_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS question_campaign_attempt (
            campaign_id TEXT NOT NULL REFERENCES question_campaign(campaign_id),
            case_id TEXT NOT NULL CHECK (char_length(case_id) BETWEEN 1 AND 256),
            attempt_number INTEGER NOT NULL CHECK (attempt_number BETWEEN 1 AND 10),
            terminal_disposition TEXT NULL CHECK (
                terminal_disposition IS NULL OR terminal_disposition IN (
                    'answered', 'clarification', 'held', 'unsupported',
                    'action_draft', 'cancelled'
                )
            ),
            terminal_reason TEXT NULL CHECK (
                terminal_reason IS NULL OR char_length(terminal_reason) BETWEEN 1 AND 128
            ),
            failure_kind TEXT NULL CHECK (
                failure_kind IS NULL OR char_length(failure_kind) BETWEEN 1 AND 128
            ),
            record JSONB NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (campaign_id, case_id, attempt_number),
            CHECK ((terminal_disposition IS NULL) <> (failure_kind IS NULL)),
            CHECK ((terminal_disposition IS NULL) = (terminal_reason IS NULL)),
            CHECK (jsonb_typeof(record) = 'object')
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_question_campaign_attempt_case "
        "ON question_campaign_attempt(campaign_id, case_id, attempt_number DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS question_campaign_completion (
            campaign_id TEXT PRIMARY KEY REFERENCES question_campaign(campaign_id),
            completed_at TIMESTAMPTZ NOT NULL,
            terminal_state TEXT NOT NULL
                CHECK (terminal_state IN ('completed', 'held', 'cancelled', 'failed')),
            terminal_reason TEXT NOT NULL
                CHECK (char_length(terminal_reason) BETWEEN 1 AND 128),
            evaluation_receipt_digest TEXT NOT NULL
                CHECK (evaluation_receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
            selected_case_ids_digest TEXT NOT NULL
                CHECK (selected_case_ids_digest ~ '^sha256:[0-9a-f]{64}$'),
            record JSONB NOT NULL,
            CHECK (jsonb_typeof(record) = 'object')
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS question_campaign_case_claim (
            campaign_id TEXT NOT NULL REFERENCES question_campaign(campaign_id),
            case_id TEXT NOT NULL CHECK (char_length(case_id) BETWEEN 1 AND 256),
            owner_id TEXT NOT NULL CHECK (char_length(owner_id) BETWEEN 1 AND 128),
            claimed_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (campaign_id, case_id),
            CHECK (expires_at > claimed_at)
        )
        """
    )
    op.execute("GRANT SELECT, INSERT ON TABLE question_campaign TO fdai_core")
    op.execute("GRANT SELECT, INSERT ON TABLE question_campaign_attempt TO fdai_core")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE question_campaign_case_claim TO fdai_core"
    )
    op.execute("GRANT SELECT, INSERT ON TABLE question_campaign_completion TO fdai_core")


def downgrade() -> None:
    """Revoke Core access while retaining durable campaign evidence."""
    op.execute("REVOKE SELECT, INSERT ON TABLE question_campaign_completion FROM fdai_core")
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE question_campaign_case_claim FROM fdai_core"
    )
    op.execute("REVOKE SELECT, INSERT ON TABLE question_campaign_attempt FROM fdai_core")
    op.execute("REVOKE SELECT, INSERT ON TABLE question_campaign FROM fdai_core")
