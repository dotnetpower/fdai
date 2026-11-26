"""Persist conversation policy transition decision-evidence bindings."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_conversation_policy_evidence_20260907"
down_revision: str | Sequence[str] | None = "operator_inventory_invalidation_read_20260906"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables = ("conversation_assurance_policy_transition",)
rollback = {
    "strategy": "drop-conversation-policy-transition-decision-evidence-columns",
    "restores": "operator_inventory_invalidation_read_20260906",
    "requires": "conversation-assurance-policy-writers-stopped",
}


def upgrade() -> None:
    """Add paired content-addressed admission evidence to policy transitions."""

    op.execute(
        """
        ALTER TABLE conversation_assurance_policy_transition
            ADD COLUMN decision_evidence_receipt_digest TEXT,
            ADD COLUMN decision_evidence_verification_bundle_digest TEXT,
            ADD CONSTRAINT ck_assurance_policy_transition_decision_evidence_pair
                CHECK (
                    (decision_evidence_receipt_digest IS NULL)
                    = (decision_evidence_verification_bundle_digest IS NULL)
                ),
            ADD CONSTRAINT ck_assurance_policy_transition_receipt_digest
                CHECK (
                    decision_evidence_receipt_digest IS NULL
                    OR decision_evidence_receipt_digest ~ '^sha256:[a-f0-9]{64}$'
                ),
            ADD CONSTRAINT ck_assurance_policy_transition_bundle_digest
                CHECK (
                    decision_evidence_verification_bundle_digest IS NULL
                    OR decision_evidence_verification_bundle_digest
                        ~ '^sha256:[a-f0-9]{64}$'
                );
        """
    )


def downgrade() -> None:
    """Remove transition admission evidence after policy writers stop."""

    op.execute(
        """
        ALTER TABLE conversation_assurance_policy_transition
            DROP CONSTRAINT IF EXISTS ck_assurance_policy_transition_bundle_digest,
            DROP CONSTRAINT IF EXISTS ck_assurance_policy_transition_receipt_digest,
            DROP CONSTRAINT IF EXISTS ck_assurance_policy_transition_decision_evidence_pair,
            DROP COLUMN IF EXISTS decision_evidence_verification_bundle_digest,
            DROP COLUMN IF EXISTS decision_evidence_receipt_digest;
        """
    )
