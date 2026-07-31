"""conversation assurance policy candidates and transitions

Revision ID: 20260731_0063
Revises: 20260731_0062
Create Date: 2026-07-31 00:00:01+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260731_0063"
down_revision: str | None = "20260731_0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE conversation_assurance_policy_candidate (
            candidate_id TEXT PRIMARY KEY,
            principal_scope TEXT NOT NULL,
            cluster_id TEXT NOT NULL,
            target TEXT NOT NULL CHECK (
                target IN (
                    'narrator_prompt', 'glossary', 'read_routing',
                    'evidence_selection', 'response_rendering',
                    'narrator_model_order'
                )
            ),
            policy_digest TEXT NOT NULL CHECK (char_length(policy_digest) = 64),
            incumbent_policy_digest TEXT NOT NULL CHECK (
                char_length(incumbent_policy_digest) = 64
            ),
            stage TEXT NOT NULL CHECK (
                stage IN (
                    'shadow', 'canary_1', 'canary_5', 'canary_25',
                    'active', 'rolled_back'
                )
            ),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (candidate_id, principal_scope)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_assurance_policy_candidate_scope_stage "
        "ON conversation_assurance_policy_candidate(principal_scope, stage)"
    )
    op.execute(
        """
        CREATE TABLE conversation_assurance_policy_transition (
            transition_key TEXT PRIMARY KEY,
            candidate_id TEXT NOT NULL,
            principal_scope TEXT NOT NULL,
            from_stage TEXT NOT NULL,
            to_stage TEXT NOT NULL,
            reasons TEXT[] NOT NULL,
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            FOREIGN KEY (candidate_id, principal_scope)
                REFERENCES conversation_assurance_policy_candidate(candidate_id, principal_scope),
            CHECK (cardinality(reasons) BETWEEN 1 AND 16),
            CHECK (from_stage IN (
                'shadow', 'canary_1', 'canary_5', 'canary_25',
                'active', 'rolled_back'
            )),
            CHECK (to_stage IN (
                'shadow', 'canary_1', 'canary_5', 'canary_25',
                'active', 'rolled_back'
            ))
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_assurance_policy_transition_candidate_time "
        "ON conversation_assurance_policy_transition("
        "principal_scope, candidate_id, occurred_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS conversation_assurance_policy_transition")
    op.execute("DROP TABLE IF EXISTS conversation_assurance_policy_candidate")
