"""llm_invocation: durable measured token and cost facts

Revision ID: 20260716_0018
Revises: 20260715_0017
Create Date: 2026-07-16 07:15:00+09:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260716_0018"
down_revision: str | None = "20260715_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS llm_invocation (
            invocation_id BIGSERIAL PRIMARY KEY,
            occurred_at TIMESTAMPTZ NOT NULL,
            correlation_id TEXT NOT NULL,
            capability_id TEXT NOT NULL,
            model_key TEXT NOT NULL,
            tier TEXT NOT NULL,
            mode TEXT NOT NULL CHECK (mode IN ('shadow', 'enforce')),
            prompt_tokens BIGINT NOT NULL CHECK (prompt_tokens >= 0),
            completion_tokens BIGINT NOT NULL CHECK (completion_tokens >= 0),
            cost NUMERIC(24, 12) CHECK (cost >= 0),
            currency TEXT,
            UNIQUE (
                occurred_at, correlation_id, capability_id, model_key, tier, mode,
                prompt_tokens, completion_tokens
            )
        );
        CREATE INDEX IF NOT EXISTS ix_llm_invocation_occurred_at
            ON llm_invocation (occurred_at DESC);
        CREATE INDEX IF NOT EXISTS ix_llm_invocation_correlation_id
            ON llm_invocation (correlation_id);

        CREATE TABLE IF NOT EXISTS report_signal (
            signal_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            category TEXT NOT NULL CHECK (category IN ('workload', 'security')),
            severity TEXT NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low')),
            resource_ref TEXT NOT NULL,
            title TEXT NOT NULL,
            detail TEXT NOT NULL,
            occurred_at TIMESTAMPTZ NOT NULL,
            evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        );
        CREATE INDEX IF NOT EXISTS ix_report_signal_occurred_at
            ON report_signal (occurred_at DESC);
        CREATE INDEX IF NOT EXISTS ix_report_signal_category
            ON report_signal (category, occurred_at DESC);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS report_signal;")
    op.execute("DROP TABLE IF EXISTS llm_invocation;")
