"""skill_proposal: durable reviewed runtime skill drafts

Revision ID: 20260717_0026
Revises: 20260717_0025
Create Date: 2026-07-17 09:00:00+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260717_0026"
down_revision: str | None = "20260717_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE skill_proposal (
            proposal_id TEXT PRIMARY KEY,
            skill_name TEXT NOT NULL,
            content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
            markdown BYTEA NOT NULL,
            proposed_by_agent TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            state TEXT NOT NULL CHECK (
                state IN ('draft', 'approved', 'rejected', 'materialized')
            ),
            reviewed_by TEXT,
            review_reason TEXT,
            reviewed_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (
                (state = 'draft' AND reviewed_by IS NULL AND reviewed_at IS NULL)
                OR (state <> 'draft' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)
            )
        );
        """
    )
    op.execute("CREATE INDEX idx_skill_proposal_state ON skill_proposal(state, created_at);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_skill_proposal_state;")
    op.execute("DROP TABLE IF EXISTS skill_proposal;")
