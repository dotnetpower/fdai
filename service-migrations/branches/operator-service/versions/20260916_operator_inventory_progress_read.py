"""Grant Operator read-only access to sanitized inventory progress records."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_inventory_progress_read_20260916"
down_revision: str | Sequence[str] | None = "operator_browser_evidence_workspace_20260915"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ()
migration_prerequisites = {
    "service": "core-control-plane",
    "revision": "core_inventory_progress_20260916",
}
rollback = {
    "strategy": "revoke-operator-inventory-progress-read",
    "restores": "operator_browser_evidence_workspace_20260915",
    "requires": "operator-runtime-stopped",
}


def upgrade() -> None:
    """Expose only immutable sanitized progress records to Operator."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE inventory_progress_event
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE inventory_progress_event TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove the read projection without changing Core-owned records."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE inventory_progress_event
        FROM fdai_operator;
        """
    )
