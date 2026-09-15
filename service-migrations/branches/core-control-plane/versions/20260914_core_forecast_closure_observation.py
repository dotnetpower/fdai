"""Retain observation evidence for every forecast evaluation closure."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_forecast_closure_observation_20260914"
down_revision: str | Sequence[str] | None = "core_cost_governance_review_20260913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("forecast_episode",)
rollback = {
    "strategy": "drop-forecast-closure-observation-after-export",
    "restores": "core_cost_governance_review_20260913",
    "requires": "forecast-writers-stopped-and-closure-observations-exported",
}


def upgrade() -> None:
    """Add nullable evidence without inventing observations for legacy closures."""
    op.execute(
        """
        ALTER TABLE forecast_episode
            ADD COLUMN closure_observation JSONB,
            ADD CONSTRAINT forecast_closure_observation_object
                CHECK (
                    closure_observation IS NULL
                    OR (
                        state = 'closed'
                        AND jsonb_typeof(closure_observation) = 'object'
                    )
                );
        """
    )


def downgrade() -> None:
    """Remove retained evidence only after writers stop and records are exported."""
    op.execute(
        "ALTER TABLE forecast_episode "
        "DROP CONSTRAINT forecast_closure_observation_object, "
        "DROP COLUMN closure_observation"
    )
