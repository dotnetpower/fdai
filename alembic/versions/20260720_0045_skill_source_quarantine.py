"""durable skill source registry and quarantine

Revision ID: 20260720_0045
Revises: 20260720_0044
Create Date: 2026-07-20 22:30:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260720_0045"
down_revision: str | None = "20260720_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE skill_source (
            source_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL CHECK (kind = 'github_repository'),
            location TEXT NOT NULL,
            trust_tier TEXT NOT NULL CHECK (trust_tier = 'organization_approved'),
            owner TEXT NOT NULL,
            allowed_path TEXT NOT NULL,
            authentication_audience_ref TEXT NOT NULL,
            refresh_policy TEXT NOT NULL CHECK (refresh_policy IN ('manual', 'scheduled')),
            refresh_interval_seconds INTEGER NOT NULL CHECK (
                refresh_interval_seconds BETWEEN 300 AND 604800
            ),
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        );
        CREATE TABLE skill_quarantine (
            quarantine_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES skill_source(source_id),
            source_revision TEXT NOT NULL,
            artifact_digest TEXT NOT NULL CHECK (char_length(artifact_digest) = 64),
            files JSONB NOT NULL CHECK (jsonb_typeof(files) = 'array'),
            publisher_signature BYTEA NOT NULL CHECK (octet_length(publisher_signature) = 64),
            fetched_at TIMESTAMPTZ NOT NULL,
            scanner_version TEXT,
            findings JSONB NOT NULL DEFAULT '[]'::jsonb,
            verdict TEXT CHECK (verdict IS NULL OR verdict IN ('pass', 'block')),
            state TEXT NOT NULL CHECK (
                state IN ('fetched', 'passed', 'blocked', 'proposed', 'revoked')
            ),
            prior_installed_digest TEXT CHECK (
                prior_installed_digest IS NULL OR char_length(prior_installed_digest) = 64
            )
        );
        CREATE INDEX skill_quarantine_source_idx
            ON skill_quarantine (source_id, fetched_at DESC, quarantine_id);
        CREATE TABLE skill_update_candidate (
            candidate_id TEXT PRIMARY KEY,
            quarantine_id TEXT NOT NULL UNIQUE REFERENCES skill_quarantine(quarantine_id),
            artifact_digest TEXT NOT NULL CHECK (char_length(artifact_digest) = 64),
            prior_installed_digest TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            disabled BOOLEAN NOT NULL DEFAULT TRUE CHECK (disabled = TRUE)
        );
        CREATE TABLE skill_revocation (
            revocation_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES skill_source(source_id),
            artifact_digest TEXT NOT NULL CHECK (char_length(artifact_digest) = 64),
            reason TEXT NOT NULL,
            revoked_at TIMESTAMPTZ NOT NULL
        );
        CREATE TABLE skill_source_refresh_state (
            source_id TEXT PRIMARY KEY REFERENCES skill_source(source_id),
            last_refresh_at TIMESTAMPTZ,
            next_refresh_at TIMESTAMPTZ,
            last_etag TEXT,
            last_revision TEXT,
            error_count INTEGER NOT NULL DEFAULT 0 CHECK (error_count >= 0),
            retry_at TIMESTAMPTZ,
            last_error_kind TEXT
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE skill_source_refresh_state;
        DROP TABLE skill_revocation;
        DROP TABLE skill_update_candidate;
        DROP TABLE skill_quarantine;
        DROP TABLE skill_source;
        """
    )
