"""add legal hold to browser evidence artifacts

Revision ID: 20260814_0083
Revises: 20260814_0082
Create Date: 2026-08-14 00:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260814_0083"
down_revision: str | None = "20260814_0082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE browser_evidence_artifact
            ADD COLUMN legal_hold BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN legal_hold_ref TEXT,
            ADD COLUMN legal_hold_at TIMESTAMPTZ,
            ADD CONSTRAINT ck_browser_evidence_legal_hold_consistent CHECK (
                (legal_hold = TRUE
                 AND legal_hold_ref IS NOT NULL
                 AND length(legal_hold_ref) BETWEEN 1 AND 512
                 AND legal_hold_at IS NOT NULL)
                OR
                (legal_hold = FALSE
                 AND legal_hold_ref IS NULL
                 AND legal_hold_at IS NULL)
            );
        CREATE INDEX browser_evidence_artifact_purge_idx
            ON browser_evidence_artifact (expires_at, artifact_id)
            WHERE legal_hold = FALSE;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX browser_evidence_artifact_purge_idx;
        ALTER TABLE browser_evidence_artifact
            DROP CONSTRAINT ck_browser_evidence_legal_hold_consistent,
            DROP COLUMN legal_hold_at,
            DROP COLUMN legal_hold_ref,
            DROP COLUMN legal_hold;
        """
    )
