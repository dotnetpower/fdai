"""Grant the Operator read-only access to Core's latest entitlement notice."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_entitlement_state_read_20261001"
down_revision: str | Sequence[str] | None = "operator_authentication_receipts_20260929"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ()
migration_prerequisites = {
    "service": "core-control-plane",
    "revision": "core_licensing_entitlement_state_20261001",
}
rollback = {
    "strategy": "revoke-operator-entitlement-state-read",
    "restores": "operator_authentication_receipts_20260929",
    "requires": "operator-runtime-stopped",
}


def upgrade() -> None:
    """Expose only the singleton notice the Operator stamps on authenticated responses."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE licensing_entitlement_state
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE licensing_entitlement_state TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove the read grant without changing the Core-owned row."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE licensing_entitlement_state
        FROM fdai_operator;
        """
    )
