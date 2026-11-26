"""durable read investigation idempotency run ledger

Revision ID: 20260722_0052
Revises: 20260722_0051
Create Date: 2026-07-22 10:30:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260722_0052"
down_revision: str | None = "20260722_0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE read_investigation_run (
            owner_principal_id TEXT NOT NULL CHECK (
                char_length(owner_principal_id) BETWEEN 1 AND 256
            ),
            idempotency_key TEXT NOT NULL CHECK (
                char_length(idempotency_key) BETWEEN 1 AND 256
            ),
            request_digest TEXT NOT NULL CHECK (
                request_digest ~ '^[0-9a-f]{64}$'
            ),
            request JSONB NOT NULL,
            mode TEXT NOT NULL CHECK (mode IN ('direct', 'streamed')),
            state TEXT NOT NULL CHECK (
                state IN ('claimed', 'running', 'completed', 'failed', 'expired')
            ),
            revision INTEGER NOT NULL CHECK (revision >= 1),
            attempt_count INTEGER NOT NULL DEFAULT 1 CHECK (
                attempt_count BETWEEN 1 AND 3
            ),
            lease_owner TEXT CHECK (
                lease_owner IS NULL OR char_length(lease_owner) BETWEEN 1 AND 256
            ),
            lease_token TEXT CHECK (
                lease_token IS NULL OR char_length(lease_token) BETWEEN 1 AND 256
            ),
            lease_expires_at TIMESTAMPTZ,
            result JSONB,
            usage JSONB,
            failure_reason TEXT CHECK (
                failure_reason IS NULL OR char_length(failure_reason) BETWEEN 1 AND 256
            ),
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            retention_until TIMESTAMPTZ NOT NULL,
            terminal_at TIMESTAMPTZ,
            PRIMARY KEY (owner_principal_id, idempotency_key),
            CHECK (created_at <= updated_at AND updated_at <= retention_until),
            CHECK (attempt_count <= revision),
            CHECK (
                usage IS NULL
                OR (
                    jsonb_typeof(usage) = 'object'
                    AND (usage ? 'tool_calls')
                    AND (usage ? 'execution_duration_ms')
                    AND (usage ? 'reserved_cost_microusd')
                    AND (usage ? 'measured_cost_microusd')
                    AND (
                        usage
                        - 'tool_calls'
                        - 'execution_duration_ms'
                        - 'reserved_cost_microusd'
                        - 'measured_cost_microusd'
                    ) = '{}'::jsonb
                    AND jsonb_typeof(usage->'tool_calls') = 'number'
                    AND jsonb_typeof(usage->'execution_duration_ms') = 'number'
                    AND jsonb_typeof(usage->'reserved_cost_microusd') = 'number'
                    AND (
                        jsonb_typeof(usage->'measured_cost_microusd') = 'number'
                        OR jsonb_typeof(usage->'measured_cost_microusd') = 'null'
                    )
                    AND (usage->>'tool_calls')::integer >= 0
                    AND (usage->>'execution_duration_ms')::integer >= 0
                    AND (usage->>'reserved_cost_microusd')::bigint >= 0
                    AND (
                        jsonb_typeof(usage->'measured_cost_microusd') = 'null'
                        OR (usage->>'measured_cost_microusd')::bigint >= 0
                    )
                )
            ),
            CHECK (
                (state IN ('claimed', 'running')
                    AND lease_owner IS NOT NULL
                    AND lease_token IS NOT NULL
                    AND lease_expires_at IS NOT NULL
                    AND result IS NULL
                    AND usage IS NULL
                    AND failure_reason IS NULL
                    AND terminal_at IS NULL)
                OR (state = 'completed'
                    AND lease_owner IS NULL
                    AND lease_token IS NULL
                    AND lease_expires_at IS NULL
                    AND result IS NOT NULL
                    AND usage IS NOT NULL
                    AND failure_reason IS NULL
                    AND terminal_at IS NOT NULL
                    AND terminal_at = updated_at)
                OR (state IN ('failed', 'expired')
                    AND lease_owner IS NULL
                    AND lease_token IS NULL
                    AND lease_expires_at IS NULL
                    AND result IS NULL
                    AND usage IS NOT NULL
                    AND failure_reason IS NOT NULL
                    AND terminal_at IS NOT NULL
                    AND terminal_at = updated_at)
            )
        );

        CREATE INDEX ix_read_investigation_run_claim_lease
            ON read_investigation_run (lease_expires_at, owner_principal_id, idempotency_key)
            WHERE state IN ('claimed', 'running');

        CREATE INDEX ix_read_investigation_run_retention
            ON read_investigation_run (retention_until, owner_principal_id, idempotency_key)
            WHERE state IN ('completed', 'failed', 'expired');
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS read_investigation_run;")
