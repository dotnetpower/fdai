"""conversation assurance single-use trial evidence

Revision ID: 20260731_0064
Revises: 20260731_0063
Create Date: 2026-07-31 00:00:02+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260731_0064"
down_revision: str | None = "20260731_0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE conversation_assurance_policy_transition ADD COLUMN evidence_digest TEXT"
    )
    op.execute(
        "UPDATE conversation_assurance_policy_transition "
        "SET evidence_digest = transition_key WHERE evidence_digest IS NULL"
    )
    op.execute(
        "ALTER TABLE conversation_assurance_policy_transition "
        "ALTER COLUMN evidence_digest SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE conversation_assurance_policy_transition "
        "ADD CONSTRAINT ck_assurance_policy_transition_evidence_digest "
        "CHECK (char_length(evidence_digest) = 64)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_assurance_policy_transition_candidate_evidence "
        "ON conversation_assurance_policy_transition(candidate_id, evidence_digest)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_assurance_policy_transition_candidate_evidence")
    op.execute(
        "ALTER TABLE conversation_assurance_policy_transition "
        "DROP CONSTRAINT IF EXISTS ck_assurance_policy_transition_evidence_digest"
    )
    op.execute(
        "ALTER TABLE conversation_assurance_policy_transition DROP COLUMN IF EXISTS evidence_digest"
    )
