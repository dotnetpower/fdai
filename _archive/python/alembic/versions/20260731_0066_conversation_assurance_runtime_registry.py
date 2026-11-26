"""conversation assurance runtime registry

Revision ID: 20260731_0066
Revises: 20260731_0065
Create Date: 2026-07-31 00:00:04+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260731_0066"
down_revision: str | None = "20260731_0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE conversation_assurance_policy_runtime (
            principal_scope TEXT NOT NULL,
            target TEXT NOT NULL,
            candidate_id TEXT NOT NULL,
            policy_digest TEXT NOT NULL CHECK (char_length(policy_digest) = 64),
            policy_text TEXT NOT NULL CHECK (char_length(policy_text) BETWEEN 1 AND 2000),
            stage TEXT NOT NULL CHECK (stage IN (
                'shadow', 'canary_1', 'canary_5', 'canary_25', 'active', 'rolled_back'
            )),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (principal_scope, target)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE conversation_assurance_policy_publication (
            publication_key TEXT PRIMARY KEY,
            principal_scope TEXT NOT NULL,
            target TEXT NOT NULL,
            before_state JSONB,
            after_state JSONB,
            published_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_assurance_policy_publication_scope_time "
        "ON conversation_assurance_policy_publication(principal_scope, published_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS conversation_assurance_policy_publication")
    op.execute("DROP TABLE IF EXISTS conversation_assurance_policy_runtime")
