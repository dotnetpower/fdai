"""Grant Operator read access to Core-owned Cost Governance settings objects."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_cost_governance_settings_read_20260831"
down_revision: str | Sequence[str] | None = "operator_projection_update_grants_20260830"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "revoke-cost-governance-settings-operator-grants",
    "restores": "operator_projection_update_grants_20260830",
    "requires": "operator-cost-governance-settings-route-stopped",
}


def upgrade() -> None:
    """Grant SELECT on analytics snapshot and EXECUTE on the settings function."""
    op.execute(
        """
        GRANT SELECT ON TABLE cost_governance_analytics_snapshot TO fdai_operator;
        GRANT EXECUTE ON FUNCTION fdai_set_cost_governance_enabled(
            TEXT, TEXT, BOOLEAN, BIGINT, TEXT
        ) TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Revoke Operator access to Core-owned settings objects."""
    op.execute(
        """
        REVOKE EXECUTE ON FUNCTION fdai_set_cost_governance_enabled(
            TEXT, TEXT, BOOLEAN, BIGINT, TEXT
        ) FROM fdai_operator;
        REVOKE SELECT ON TABLE cost_governance_analytics_snapshot FROM fdai_operator;
        """
    )
