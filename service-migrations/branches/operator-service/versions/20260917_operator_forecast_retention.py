"""Expose aggregate case-history retention debt without private case access."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_forecast_retention_20260917"
down_revision: str | Sequence[str] | None = "operator_inventory_progress_read_20260916"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "drop-aggregate-forecast-retention-view",
    "restores": "operator_inventory_progress_read_20260916",
    "requires": "operator-runtime-stopped",
}


def upgrade() -> None:
    """Grant only read access to the two derived lifecycle counters."""
    op.execute(
        """
        CREATE VIEW operator_forecast_retention
        WITH (security_barrier = true) AS
        SELECT COUNT(*) FILTER (
                   WHERE deletion_started_at IS NOT NULL AND deleted_at IS NULL
               ) AS pending,
               COUNT(*) FILTER (
                   WHERE deleted_at IS NULL AND deletion_due_at < now()
               ) AS overdue
          FROM case_history;
        REVOKE ALL PRIVILEGES ON TABLE operator_forecast_retention FROM PUBLIC;
        GRANT SELECT ON TABLE operator_forecast_retention TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove the aggregate read surface without changing case-history data."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE operator_forecast_retention FROM fdai_operator;
        DROP VIEW operator_forecast_retention;
        """
    )
