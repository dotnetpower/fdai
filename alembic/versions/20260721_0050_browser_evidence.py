"""immutable browser evidence artifacts

Revision ID: 20260721_0050
Revises: 20260721_0049
Create Date: 2026-07-21 15:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260721_0050"
down_revision: str | None = "20260721_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE browser_evidence_artifact (
            artifact_id TEXT PRIMARY KEY CHECK (
                artifact_id ~ '^sha256:[0-9a-f]{64}$'
            ),
            content_digest TEXT NOT NULL UNIQUE CHECK (
                content_digest ~ '^[0-9a-f]{64}$'
            ),
            policy_id TEXT NOT NULL CHECK (length(policy_id) > 0),
            policy_version INTEGER NOT NULL CHECK (policy_version > 0),
            canonical_source_url TEXT NOT NULL CHECK (
                canonical_source_url LIKE 'https://%'
            ),
            canonical_final_url TEXT NOT NULL CHECK (
                canonical_final_url LIKE 'https://%'
            ),
            captured_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            selectors JSONB NOT NULL CHECK (jsonb_typeof(selectors) = 'array'),
            screenshot BYTEA,
            visible_text TEXT,
            aria_snapshot TEXT,
            screenshot_hash TEXT CHECK (
                screenshot_hash IS NULL OR screenshot_hash ~ '^[0-9a-f]{64}$'
            ),
            text_hash TEXT CHECK (
                text_hash IS NULL OR text_hash ~ '^[0-9a-f]{64}$'
            ),
            snapshot_hash TEXT CHECK (
                snapshot_hash IS NULL OR snapshot_hash ~ '^[0-9a-f]{64}$'
            ),
            redaction_manifest JSONB NOT NULL CHECK (
                jsonb_typeof(redaction_manifest) = 'array'
            ),
            browser_version TEXT NOT NULL CHECK (length(browser_version) > 0),
            chain_of_custody_audit_ref TEXT NOT NULL UNIQUE CHECK (
                length(chain_of_custody_audit_ref) > 0
            ),
            prompt_injection_findings JSONB NOT NULL CHECK (
                jsonb_typeof(prompt_injection_findings) = 'array'
            ),
            isolation JSONB NOT NULL CHECK (jsonb_typeof(isolation) = 'object'),
            untrusted BOOLEAN NOT NULL DEFAULT TRUE CHECK (untrusted = TRUE),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (captured_at < expires_at),
            CHECK (artifact_id = 'sha256:' || content_digest)
        );
        CREATE INDEX browser_evidence_artifact_policy_idx
            ON browser_evidence_artifact (
                policy_id, policy_version, captured_at DESC, artifact_id
            );
        CREATE INDEX browser_evidence_artifact_retention_idx
            ON browser_evidence_artifact (expires_at, artifact_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE browser_evidence_artifact;")
