"""durable automation blueprint candidates

Revision ID: 20260720_0043
Revises: 20260720_0042
Create Date: 2026-07-20 17:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260720_0043"
down_revision: str | None = "20260720_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE automation_blueprint_candidate (
            candidate_id TEXT PRIMARY KEY,
            dedup_key TEXT NOT NULL CHECK (char_length(dedup_key) = 64),
            normalized_task_intent TEXT NOT NULL CHECK (
                char_length(normalized_task_intent) BETWEEN 1 AND 512
            ),
            schedule_class TEXT NOT NULL CHECK (char_length(schedule_class) BETWEEN 1 AND 64),
            schedule_expression TEXT NOT NULL CHECK (
                char_length(schedule_expression) BETWEEN 1 AND 128
            ),
            event_type TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            resource_scope TEXT NOT NULL,
            delivery_intent TEXT NOT NULL,
            required_tools JSONB NOT NULL CHECK (jsonb_typeof(required_tools) = 'array'),
            isolation_profile JSONB NOT NULL CHECK (jsonb_typeof(isolation_profile) = 'object'),
            estimated_cost_microusd BIGINT NOT NULL CHECK (estimated_cost_microusd >= 0),
            evidence_fingerprints JSONB NOT NULL CHECK (
                jsonb_typeof(evidence_fingerprints) = 'array'
                AND jsonb_array_length(evidence_fingerprints) > 0
            ),
            proposer TEXT NOT NULL,
            confidence DOUBLE PRECISION NOT NULL CHECK (confidence BETWEEN 0 AND 1),
            created_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL CHECK (expires_at > created_at),
            state TEXT NOT NULL CHECK (
                state IN ('draft', 'accepted', 'rejected', 'expired', 'materialized')
            ),
            enabled BOOLEAN NOT NULL DEFAULT FALSE CHECK (enabled = FALSE),
            shadow_only BOOLEAN NOT NULL DEFAULT TRUE CHECK (shadow_only = TRUE),
            mutation_tool_ids JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (
                mutation_tool_ids = '[]'::jsonb
            ),
            reviewed_by TEXT,
            review_reason TEXT,
            resulting_task_id TEXT,
            realized_usage_count BIGINT NOT NULL DEFAULT 0 CHECK (realized_usage_count >= 0)
        );
        CREATE UNIQUE INDEX automation_blueprint_active_dedup_idx
            ON automation_blueprint_candidate (dedup_key)
            WHERE state IN ('draft', 'accepted');
        CREATE INDEX automation_blueprint_state_expiry_idx
            ON automation_blueprint_candidate (state, expires_at, candidate_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE automation_blueprint_candidate;")
