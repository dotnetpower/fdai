"""Preserve provider event and FDAI ingestion time in inventory history."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_inventory_temporal_axes_20260916"
down_revision: str | Sequence[str] | None = "core_alert_forecast_merge_20260915"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("inventory_observation_journal",)
rollback = {
    "strategy": "drop-additive-inventory-temporal-axes",
    "restores": "core_alert_forecast_merge_20260915",
    "requires": "inventory-observation-writers-stopped",
}


def upgrade() -> None:
    """Add temporal axes and backfill retained rows without changing identities."""

    # The migration transaction holds the table lock until the update trigger is restored,
    # so no concurrent session can observe a writable journal.
    op.execute(
        """
        ALTER TABLE inventory_observation_journal
            ADD COLUMN provider_event_at TIMESTAMPTZ,
            ADD COLUMN ingested_at TIMESTAMPTZ;

        ALTER TABLE inventory_observation_journal
            DISABLE TRIGGER inventory_observation_journal_no_modify;

        UPDATE inventory_observation_journal
        SET ingested_at = recorded_at
        WHERE ingested_at IS NULL;

        ALTER TABLE inventory_observation_journal
            ENABLE TRIGGER inventory_observation_journal_no_modify;

        ALTER TABLE inventory_observation_journal
            ALTER COLUMN ingested_at SET NOT NULL;
        """
    )


def downgrade() -> None:
    """Remove only the additive axes after stopping inventory writers."""

    op.execute(
        """
        ALTER TABLE inventory_observation_journal
            DROP COLUMN ingested_at,
            DROP COLUMN provider_event_at;
        """
    )
