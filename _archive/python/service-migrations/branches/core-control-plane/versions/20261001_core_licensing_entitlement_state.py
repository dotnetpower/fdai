"""Store Core's latest entitlement notice for the Console watermark.

Core resolves its license entitlement on a fixed cadence and records one derived
notice with its observation time. The Operator only reads the row to stamp
authenticated responses, so the watermark follows Core's single license authority
instead of a second resolver.

The row is a singleton. A write never moves `observed_at` backward, so a replica that
resolved earlier cannot replace a newer notice. The notice is a closed vocabulary, and
an unknown value cannot be stored. Core reads and writes the row; no role receives
DELETE. The Operator's read grant lives in the Operator branch.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_licensing_entitlement_state_20261001"
down_revision: str | Sequence[str] | None = "core_operator_receipt_source_20260930"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
migration_owner = "core-control-plane"
owned_tables: tuple[str, ...] = ("licensing_entitlement_state",)
rollback = {
    "strategy": "drop-licensing-entitlement-state-singleton",
    "restores": "core_operator_receipt_source_20260930",
    "requires": "core-stopped",
}


def upgrade() -> None:
    """Create the singleton notice row and grant Core its only writer access."""
    op.execute(
        """
        CREATE TABLE licensing_entitlement_state (
            singleton BOOLEAN PRIMARY KEY DEFAULT TRUE,
            notice TEXT NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT licensing_entitlement_state_is_singleton CHECK (singleton),
            CONSTRAINT licensing_entitlement_state_notice
                CHECK (notice IN ('none', 'evaluation-ended', 'not-activated'))
        );

        REVOKE ALL ON TABLE licensing_entitlement_state FROM PUBLIC;
        GRANT SELECT, INSERT, UPDATE ON TABLE licensing_entitlement_state TO fdai_core;
        """
    )


def downgrade() -> None:
    """Drop the notice row; the Operator read grant must be revoked first."""
    op.execute("DROP TABLE licensing_entitlement_state;")
