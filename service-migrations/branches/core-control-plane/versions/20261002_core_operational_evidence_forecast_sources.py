"""Allow the operational-evidence verifier to read forecast source transitions.

Revision ID: core_operational_evidence_forecast_sources_20261002
Revises: core_licensing_entitlement_state_20261001
Create Date: 2026-10-02
"""

from __future__ import annotations

from alembic import op

revision: str = "core_operational_evidence_forecast_sources_20261002"
down_revision: str | None = "core_licensing_entitlement_state_20261001"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None
migration_owner = "core-control-plane"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "revoke-operational-evidence-forecast-source-read",
    "restores": "core_licensing_entitlement_state_20261001",
    "requires": "operational-evidence-verifier-stopped",
}


def upgrade() -> None:
    op.execute(
        """
        GRANT SELECT ON TABLE
            operational_state_transition_batch,
            operational_state_transition,
            operational_state_transition_coverage
        TO fdai_operational_evidence_verifier;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        REVOKE SELECT ON TABLE
            operational_state_transition_coverage,
            operational_state_transition,
            operational_state_transition_batch
        FROM fdai_operational_evidence_verifier;
        """
    )
