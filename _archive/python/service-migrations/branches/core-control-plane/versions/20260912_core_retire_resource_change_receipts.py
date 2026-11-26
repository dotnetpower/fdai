"""Retire redundant Resource-change processing receipts."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_retire_resource_change_receipts_20260912"
down_revision: str | Sequence[str] | None = "core_resource_change_receipts_20260912"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("inventory_change_event_receipt",)
rollback = {
    "strategy": "restore-inventory-change-event-receipt",
    "restores": "core_resource_change_receipts_20260912",
    "requires": "inventory-change-writers-stopped",
}


def upgrade() -> None:
    op.execute("DROP TABLE inventory_change_event_receipt")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE inventory_change_event_receipt (
            source_event_id TEXT PRIMARY KEY
                CHECK (char_length(source_event_id) BETWEEN 1 AND 512),
            outcome TEXT NOT NULL
                CHECK (outcome IN ('applied', 'ordering_rejected', 'snapshot_covered')),
            processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        REVOKE ALL PRIVILEGES ON TABLE inventory_change_event_receipt
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT ON TABLE inventory_change_event_receipt TO fdai_core
        """
    )
