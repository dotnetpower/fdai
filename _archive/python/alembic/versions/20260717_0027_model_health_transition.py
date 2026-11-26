"""model_health_transition: durable redacted routing health telemetry

Revision ID: 20260717_0027
Revises: 20260717_0026
Create Date: 2026-07-17 09:30:00+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260717_0027"
down_revision: str | None = "20260717_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE model_health_transition (
            transition_id BIGSERIAL PRIMARY KEY,
            model_role TEXT NOT NULL,
            deployment TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('unhealthy', 'recovered', 'selected')),
            failure_kind TEXT CHECK (
                failure_kind IS NULL OR failure_kind IN (
                    'auth', 'rate_limit', 'overloaded', 'timeout', 'transport', 'unknown'
                )
            ),
            failure_count INTEGER NOT NULL CHECK (failure_count >= 0),
            cooldown_seconds INTEGER NOT NULL CHECK (cooldown_seconds >= 0),
            recorded_at TIMESTAMPTZ NOT NULL,
            reason TEXT NOT NULL DEFAULT ''
        );
        """
    )
    op.execute(
        "CREATE INDEX idx_model_health_transition_role_deployment "
        "ON model_health_transition(model_role, deployment, transition_id DESC);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_model_health_transition_role_deployment;")
    op.execute("DROP TABLE IF EXISTS model_health_transition;")
