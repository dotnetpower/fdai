"""question space campaign and case-attempt ledgers

Revision ID: 20260819_0086
Revises: 20260817_0085
Create Date: 2026-08-19 00:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260819_0086"
down_revision: str | None = "20260817_0085"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE question_campaign (
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
        "CREATE INDEX idx_question_campaign_source_started "
        "ON question_campaign(source_revision, started_at DESC)"
    )
    op.execute(
        "CREATE INDEX idx_question_campaign_universe_started "
        "ON question_campaign(question_universe_digest, started_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE question_campaign_attempt (
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
        "CREATE INDEX idx_question_campaign_attempt_case "
        "ON question_campaign_attempt(campaign_id, case_id, attempt_number DESC)"
    )
    op.execute(
        """
        CREATE TABLE question_campaign_completion (
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
        CREATE TABLE question_campaign_case_claim (
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


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS question_campaign_case_claim")
    op.execute("DROP TABLE IF EXISTS question_campaign_completion")
    op.execute("DROP TABLE IF EXISTS question_campaign_attempt")
    op.execute("DROP TABLE IF EXISTS question_campaign")
