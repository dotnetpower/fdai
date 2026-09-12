"""Retain verified evidence references on runtime skill proposals."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_skill_proposal_evidence_20260912"
down_revision: str | Sequence[str] | None = "operator_conversation_policy_evidence_20260907"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables = ("skill_proposal",)
rollback = {
    "strategy": "retain-legacy-skill-proposal-evidence-refs",
    "restores": "operator_conversation_policy_evidence_20260907",
    "requires": "no-runtime-skill-proposal-writers",
}


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE skill_proposal
        ADD COLUMN IF NOT EXISTS evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(evidence_refs) = 'array');
        """
    )


def downgrade() -> None:
    """Retain the evidence column and data inherited from legacy revision 0090."""
