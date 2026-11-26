"""rpc_idempotency_claim: durable side-effect RPC claims

Revision ID: 20260717_0032
Revises: 20260717_0031
Create Date: 2026-07-17 16:00:00+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260717_0032"
down_revision: str | None = "20260717_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE rpc_idempotency_claim (
            key_sha256 TEXT PRIMARY KEY CHECK (key_sha256 ~ '^[a-f0-9]{64}$'),
            state TEXT NOT NULL CHECK (state IN ('claimed', 'completed')),
            response JSONB,
            claimed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at TIMESTAMPTZ,
            CHECK (
                (state = 'claimed' AND response IS NULL AND completed_at IS NULL) OR
                (state = 'completed' AND jsonb_typeof(response) = 'object' AND
                 completed_at IS NOT NULL AND completed_at >= claimed_at)
            )
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE rpc_idempotency_claim;")
