"""post-turn review ledger and operator-memory proposal queue

Revision ID: 20260720_0037
Revises: 20260718_0036
Create Date: 2026-07-20 05:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260720_0037"
down_revision: str | None = "20260718_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE post_turn_review (
            review_id TEXT PRIMARY KEY,
            principal_scope TEXT NOT NULL,
            state TEXT NOT NULL CHECK (
                state IN ('pending', 'ineligible', 'abstained', 'duplicate', 'routed', 'failed')
            ),
            reasons TEXT[] NOT NULL CHECK (cardinality(reasons) > 0),
            proposal_kind TEXT CHECK (
                proposal_kind IS NULL
                OR proposal_kind IN ('operator_memory', 'rule_hint', 'skill_draft')
            ),
            proposal_ref TEXT,
            dedup_key TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CHECK (state <> 'routed' OR proposal_ref IS NOT NULL)
        );
        CREATE INDEX idx_post_turn_review_state_updated
            ON post_turn_review(state, updated_at DESC);

        CREATE TABLE post_turn_proposal_claim (
            dedup_key TEXT PRIMARY KEY,
            review_id TEXT NOT NULL REFERENCES post_turn_review(review_id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE operator_memory_proposal (
            proposal_id TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
            scope_kind TEXT NOT NULL CHECK (scope_kind IN ('resource-group', 'resource')),
            scope_ref TEXT NOT NULL,
            category TEXT NOT NULL CHECK (
                category IN ('preference', 'override-note', 'forbidden-action', 'runbook-hint')
            ),
            body TEXT NOT NULL,
            evidence_refs TEXT[] NOT NULL CHECK (cardinality(evidence_refs) > 0),
            proposed_by_agent TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            state TEXT NOT NULL CHECK (
                state IN ('draft', 'approved', 'rejected', 'materialized')
            ),
            reviewed_by TEXT,
            review_reason TEXT,
            reviewed_at TIMESTAMPTZ,
            materialized_entry_id UUID,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (
                (state = 'draft' AND reviewed_by IS NULL AND reviewed_at IS NULL)
                OR (state <> 'draft' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)
            ),
            CHECK (
                (state = 'materialized' AND materialized_entry_id IS NOT NULL)
                OR (state <> 'materialized' AND materialized_entry_id IS NULL)
            )
        );
        CREATE INDEX idx_operator_memory_proposal_state_created
            ON operator_memory_proposal(state, created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_operator_memory_proposal_state_created;")
    op.execute("DROP TABLE IF EXISTS operator_memory_proposal;")
    op.execute("DROP TABLE IF EXISTS post_turn_proposal_claim;")
    op.execute("DROP INDEX IF EXISTS idx_post_turn_review_state_updated;")
    op.execute("DROP TABLE IF EXISTS post_turn_review;")
