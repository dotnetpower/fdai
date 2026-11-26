"""Grant Operator read access to Cost Governance live evidence and lineage."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_cost_governance_live_read_20260917"
down_revision: str | Sequence[str] | None = "operator_forecast_retention_20260917"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ()
migration_prerequisites = {
    "service": "core-control-plane",
    "revision": "core_cost_governance_live_20260917",
}
rollback = {
    "strategy": "revoke-cost-governance-live-projection-read",
    "restores": "operator_forecast_retention_20260917",
    "requires": "operator-runtime-stopped",
}


def upgrade() -> None:
    """Grant SELECT only on explicit Cost Governance evidence records."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            cost_observation_current,
            cost_governance_analytics_run_receipt,
            cost_governance_case_projection,
            cost_governance_episode,
            cost_governance_evidence,
            cost_governance_recovery,
            cost_governance_retention,
            cost_governance_settlement,
            cost_governance_effect_settlement
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE
            cost_observation_current,
            cost_governance_analytics_run_receipt,
            cost_governance_case_projection,
            cost_governance_episode,
            cost_governance_evidence,
            cost_governance_recovery,
            cost_governance_retention,
            cost_governance_settlement,
            cost_governance_effect_settlement
        TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Revoke projection reads without changing retained Core evidence."""

    op.execute(
        """
        REVOKE SELECT ON TABLE
            cost_observation_current,
            cost_governance_analytics_run_receipt,
            cost_governance_case_projection,
            cost_governance_episode,
            cost_governance_evidence,
            cost_governance_recovery,
            cost_governance_retention,
            cost_governance_settlement,
            cost_governance_effect_settlement
        FROM fdai_operator;
        """
    )
