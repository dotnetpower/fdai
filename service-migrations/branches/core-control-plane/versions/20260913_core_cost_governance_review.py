"""Persist independent Cost Governance review-only decisions."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_cost_governance_review_20260913"
down_revision: str | Sequence[str] | None = "core_effect_observation_20260913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("cost_governance_promotion_review",)
rollback = {
    "strategy": "drop-cost-promotion-reviews-after-review-readers-stop",
    "restores": "core_effect_observation_20260913",
    "requires": "cost-promotion-review-readers-stopped",
}


def upgrade() -> None:
    """Create an append-only, authority-neutral review receipt table."""

    op.execute(
        """
        CREATE TABLE cost_governance_promotion_review (
            review_id TEXT PRIMARY KEY CHECK (review_id ~ '^sha256:[0-9a-f]{64}$'),
            request_id TEXT NOT NULL UNIQUE
                CHECK (char_length(request_id) BETWEEN 1 AND 2000),
            campaign_id TEXT NOT NULL
                CHECK (char_length(campaign_id) BETWEEN 1 AND 512),
            campaign_evidence_digest TEXT NOT NULL
                CHECK (campaign_evidence_digest ~ '^sha256:[0-9a-f]{64}$'),
            revision_pin_digest TEXT NOT NULL
                CHECK (revision_pin_digest ~ '^sha256:[0-9a-f]{64}$'),
            campaign_report_digest TEXT NOT NULL
                CHECK (campaign_report_digest ~ '^sha256:[0-9a-f]{64}$'),
            target_kind TEXT NOT NULL
                CHECK (target_kind IN ('package-activation', 'action-type', 'workflow')),
            target_id TEXT NOT NULL CHECK (char_length(target_id) BETWEEN 1 AND 512),
            reviewer_identity TEXT NOT NULL
                CHECK (char_length(reviewer_identity) BETWEEN 1 AND 2000),
            decision TEXT NOT NULL CHECK (decision IN ('recommend', 'hold', 'deny')),
            rationale TEXT NOT NULL CHECK (char_length(rationale) BETWEEN 1 AND 2000),
            reviewed_at TIMESTAMPTZ NOT NULL,
            evidence_refs JSONB NOT NULL CHECK (
                jsonb_typeof(evidence_refs) = 'array'
                AND jsonb_array_length(evidence_refs) BETWEEN 1 AND 64
            ),
            retention_until TIMESTAMPTZ NOT NULL CHECK (retention_until > reviewed_at),
            approval_authority BOOLEAN NOT NULL DEFAULT FALSE CHECK (NOT approval_authority),
            execution_authority BOOLEAN NOT NULL DEFAULT FALSE CHECK (NOT execution_authority),
            promotion_authority BOOLEAN NOT NULL DEFAULT FALSE CHECK (NOT promotion_authority),
            payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object')
        );

        CREATE INDEX cost_governance_promotion_review_campaign_idx
            ON cost_governance_promotion_review (
                campaign_id, campaign_evidence_digest, revision_pin_digest,
                reviewed_at, target_kind, target_id
            );

        REVOKE ALL PRIVILEGES ON TABLE cost_governance_promotion_review
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT ON TABLE cost_governance_promotion_review TO fdai_core;
        """
    )


def downgrade() -> None:
    """Drop review receipts after all review readers stop."""

    op.execute("DROP TABLE cost_governance_promotion_review;")
